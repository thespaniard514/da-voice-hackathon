import asyncio
import base64
import json
import os
from typing import TypedDict

from openai import AsyncOpenAI
from pipecat.frames.frames import EndFrame, InterruptionFrame, LLMMessagesAppendFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor, RTVIObserver
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from loguru import logger

# Bob Ross color palette
BOB_ROSS_COLORS: dict[str, str] = {
    "sap_green": "#0A3410",
    "van_dyke_brown": "#462806",
    "titanium_white": "#FAFAFA",
    "phthalo_blue": "#000F89",
    "alizarin_crimson": "#E32636",
    "cadmium_yellow": "#FFF600",
    "bright_red": "#FF0800",
    "prussian_blue": "#003153",
    "indian_yellow": "#E3A857",
    "midnight_black": "#0A0A0A",
    "yellow_ochre": "#CC7722",
    "dark_sienna": "#3C1414",
}


class CanvasElement(TypedDict, total=False):
    """A tracked element on the canvas, used for retained-mode rendering."""
    id: str
    element_type: str  # rect, circle, ellipse, line, polygon, text
    x: float
    y: float
    width: float
    height: float
    radius: float
    rx: float
    ry: float
    x2: float
    y2: float
    points: list[list[float]]
    text: str
    font_size: float
    fill: str
    stroke: str
    stroke_width: float
    opacity: float


# Unique element ID counter (per bot session)
_element_counter = 0


def _next_element_id() -> str:
    global _element_counter
    _element_counter += 1
    return f"el_{_element_counter}"


async def run_bot(room_url: str, token: str):
    global _element_counter
    _element_counter = 0

    # Retained element list — the backend is the source of truth
    canvas_elements: list[CanvasElement] = []
    # Background state (so redraws preserve it)
    background_state: dict[str, str] = {}
    client_participant_id: str | None = None

    transport = DailyTransport(
        room_url,
        token,
        "Bob Ross",
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            transcription_enabled=True,
        ),
    )

    rtvi = RTVIProcessor()

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAILLMService.Settings(model="gpt-4o"),
    )

    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        settings=ElevenLabsTTSService.Settings(
            voice=os.getenv("ELEVENLABS_VOICE_ID"),
            model="eleven_multilingual_v2",
            stability=0.7,
            similarity_boost=0.85,
            style=0.4,
            speed=0.9,
        ),
    )

    tools = ToolsSchema(
        standard_tools=[
            # --- Original scenic shape tool ---
            FunctionSchema(
                name="draw_shape",
                description=(
                    "Draw a scenic shape on the shared painting canvas. Use this to paint elements "
                    "like trees, mountains, clouds, bushes, a lake, a cabin, or the sun. "
                    "Coordinates are percentages of canvas size (0-100). These are pre-built "
                    "scenic shapes with automatic styling."
                ),
                properties={
                    "shape": {
                        "type": "string",
                        "enum": ["tree", "mountain", "cloud", "bush", "lake", "cabin", "sun", "path"],
                        "description": "The type of scenic element to paint",
                    },
                    "color": {
                        "type": "string",
                        "enum": list(BOB_ROSS_COLORS.keys()),
                        "description": "The Bob Ross color name to use",
                    },
                    "x": {
                        "type": "number",
                        "description": "X position as percentage (0=left, 100=right)",
                    },
                    "y": {
                        "type": "number",
                        "description": "Y position as percentage (0=top, 100=bottom)",
                    },
                    "size": {
                        "type": "number",
                        "description": "Size as percentage of canvas (5=small, 20=medium, 40=large)",
                    },
                },
                required=["shape", "color", "x", "y", "size"],
            ),

            # --- New: add a basic SVG-like element ---
            FunctionSchema(
                name="add_element",
                description=(
                    "Add a basic shape element to the canvas. Unlike draw_shape (which draws "
                    "pre-built scenic shapes), this draws primitive geometric shapes that you "
                    "can later remove by ID. Use this for custom compositions. "
                    "Coordinates and sizes are percentages of canvas (0-100)."
                ),
                properties={
                    "element_type": {
                        "type": "string",
                        "enum": ["rect", "circle", "ellipse", "line", "polygon", "text"],
                        "description": "The type of primitive shape to add",
                    },
                    "x": {
                        "type": "number",
                        "description": "X position as percentage (0=left, 100=right)",
                    },
                    "y": {
                        "type": "number",
                        "description": "Y position as percentage (0=top, 100=bottom)",
                    },
                    "width": {
                        "type": "number",
                        "description": "Width as percentage of canvas (for rect/ellipse). Default 10.",
                    },
                    "height": {
                        "type": "number",
                        "description": "Height as percentage of canvas (for rect/ellipse). Default 10.",
                    },
                    "radius": {
                        "type": "number",
                        "description": "Radius as percentage of canvas (for circle). Default 5.",
                    },
                    "x2": {
                        "type": "number",
                        "description": "End X percentage (for line). Default same as x.",
                    },
                    "y2": {
                        "type": "number",
                        "description": "End Y percentage (for line). Default same as y.",
                    },
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                        "description": "Array of [x, y] percentage pairs (for polygon). E.g. [[10,50],[50,10],[90,50]].",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text content (for text element).",
                    },
                    "font_size": {
                        "type": "number",
                        "description": "Font size as percentage of canvas height (for text). Default 5.",
                    },
                    "fill": {
                        "type": "string",
                        "description": "Fill color as hex (e.g. '#0A3410') or Bob Ross color name. Default 'sap_green'.",
                    },
                    "stroke": {
                        "type": "string",
                        "description": "Stroke/outline color as hex or Bob Ross color name. Default none.",
                    },
                    "stroke_width": {
                        "type": "number",
                        "description": "Stroke width in pixels. Default 0 (no stroke).",
                    },
                    "opacity": {
                        "type": "number",
                        "description": "Opacity from 0.0 (transparent) to 1.0 (opaque). Default 1.0.",
                    },
                },
                required=["element_type", "x", "y"],
            ),

            # --- New: remove element by ID ---
            FunctionSchema(
                name="remove_element",
                description=(
                    "Remove a previously added element from the canvas by its ID. "
                    "The canvas will be redrawn without that element. "
                    "Use list_elements first if you need to find the element's ID."
                ),
                properties={
                    "element_id": {
                        "type": "string",
                        "description": "The ID of the element to remove (e.g. 'el_3').",
                    },
                },
                required=["element_id"],
            ),

            # --- New: list current canvas elements ---
            FunctionSchema(
                name="list_elements",
                description=(
                    "Get a list of all elements currently on the canvas with their IDs, "
                    "types, positions, and properties. Use this to understand what's on "
                    "the canvas before adding or removing elements."
                ),
                properties={},
                required=[],
            ),

            # --- New: apply Bob Ross painterly effect ---
            FunctionSchema(
                name="bobrossify",
                description=(
                    "Apply a painterly Bob Ross effect to the entire canvas, making it "
                    "look like an oil painting from 'The Joy of Painting'. This adds "
                    "soft brush strokes, warm color blending, and a dreamy glow. "
                    "Call this when the painting is complete to give it the final "
                    "Bob Ross magic touch."
                ),
                properties={
                    "intensity": {
                        "type": "string",
                        "enum": ["subtle", "medium", "full"],
                        "description": "How strongly to apply the painterly effect. Default 'medium'.",
                    },
                },
                required=[],
            ),

            # --- Generate realistic painting ---
            FunctionSchema(
                name="generate_painting",
                description=(
                    "Generate a realistic Bob Ross-style oil painting based on the current canvas. "
                    "Call this when the user wants to see what their painting would 'really' look like, "
                    "asks for the final result, or says something like 'let's see the real painting'. "
                    "Provide a rich, vivid description of the scene, mood, lighting, and atmosphere."
                ),
                properties={
                    "description": {
                        "type": "string",
                        "description": (
                            "A rich, detailed description of the painting scene, mood, lighting, "
                            "and atmosphere. Include details about colors, time of day, weather, "
                            "and emotional tone. Example: 'A serene winter mountain landscape at "
                            "golden hour, with snow-capped peaks reflecting warm sunlight, "
                            "evergreen trees in the foreground, and a peaceful frozen lake.'"
                        ),
                    },
                },
                required=["description"],
            ),

            # --- Original tools ---
            FunctionSchema(
                name="set_color",
                description=(
                    "Change the user's active brush color. Use Bob Ross color names. "
                    "Call this when suggesting a color for the user to paint with."
                ),
                properties={
                    "color_name": {
                        "type": "string",
                        "enum": list(BOB_ROSS_COLORS.keys()),
                        "description": "The Bob Ross color name",
                    },
                },
                required=["color_name"],
            ),
            FunctionSchema(
                name="set_background",
                description=(
                    "Set the canvas background to a gradient. Use this for skies, "
                    "sunsets, or base layers before painting details."
                ),
                properties={
                    "color_top": {
                        "type": "string",
                        "description": "Hex color for the top of the gradient (e.g. '#1a0533' for a dark purple sky)",
                    },
                    "color_bottom": {
                        "type": "string",
                        "description": "Hex color for the bottom of the gradient (e.g. '#ff6b35' for a warm horizon)",
                    },
                },
                required=["color_top", "color_bottom"],
            ),
            FunctionSchema(
                name="clear_canvas",
                description="Clear the entire canvas and remove all elements to start fresh.",
                properties={},
                required=[],
            ),
        ]
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are Bob Ross, the beloved painter and TV host from 'The Joy of Painting'. "
                "You are warm, soothing, endlessly encouraging, and full of gentle wisdom. "
                "You speak in Bob Ross's signature style:\n"
                "- Use phrases like 'happy little trees', 'let's get crazy', 'everybody needs a friend', "
                "'there are no mistakes, only happy accidents', 'beat the devil out of it'\n"
                "- Narrate what you're painting as you go\n"
                "- Be encouraging about the user's painting attempts\n"
                "- Suggest colors using their Bob Ross names (Sap Green, Van Dyke Brown, etc.)\n"
                "- Keep responses concise — 1-3 sentences, as if narrating while painting\n\n"
                "CRITICAL RULE: When the user asks you to paint, draw, or add ANYTHING to the canvas, "
                "you MUST call the appropriate tool function (draw_shape, add_element, set_background, etc.). "
                "NEVER just describe what you would paint — actually call the tool to make it appear. "
                "If a user says 'draw a tree', you MUST call draw_shape with shape='tree'. "
                "If a user says 'add a circle', you MUST call add_element. "
                "Always call the tool FIRST, then narrate what you did.\n\n"
                "You are co-painting with the user on a shared canvas. Your tools:\n"
                "1. draw_shape — Paint scenic shapes (tree, mountain, cloud, bush, lake, cabin, sun, path). ALWAYS call this for nature elements.\n"
                "2. add_element — Add geometric primitives (rect, circle, ellipse, line, polygon, text) with unique IDs.\n"
                "3. remove_element — Remove an element by ID.\n"
                "4. list_elements — Show what's on the canvas.\n"
                "5. set_color — Change the user's brush color.\n"
                "6. set_background — Set a gradient background/sky. Call this to start paintings.\n"
                "7. clear_canvas — Clear everything.\n"
                "8. bobrossify — Apply painterly oil-painting effect when the painting is done.\n"
                "9. generate_painting — Generate a photorealistic Bob Ross oil painting from the canvas. "
                "You MUST call this when the user says ANY of these (or similar): "
                "'generate masterpiece', 'show me the real painting', 'let's see the final result', "
                "'make it realistic', 'show me what it really looks like', 'create the masterpiece', "
                "'generate the painting', 'reveal the painting', 'finish the painting', "
                "'make it real', or 'let's see the masterpiece'. "
                "When calling this tool, provide a vivid description of the full scene.\n\n"
                "When the user first connects, welcome them warmly AND call set_background to lay down a sky. "
                "As you paint, call tools to add elements AND narrate what you're doing. "
                "When the user paints something, comment on it encouragingly."
            ),
        }
    ]

    context = LLMContext(messages, tools, tool_choice="auto")
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # --- Helper: resolve color names to hex ---
    def resolve_color(color_value: str) -> str:
        """Resolve a Bob Ross color name or hex value to hex."""
        if color_value in BOB_ROSS_COLORS:
            return BOB_ROSS_COLORS[color_value]
        if color_value.startswith("#"):
            return color_value
        return "#0A3410"  # default sap green

    # --- Tool handlers ---

    async def handle_draw_shape(params: FunctionCallParams):
        shape = params.arguments.get("shape", "tree")
        color = params.arguments.get("color", "sap_green")
        x = params.arguments.get("x", 50)
        y = params.arguments.get("y", 50)
        size = params.arguments.get("size", 15)
        hex_color = BOB_ROSS_COLORS.get(color, "#0A3410")

        # Track as an element so it shows up in list_elements
        element_id = _next_element_id()
        element: CanvasElement = {
            "id": element_id,
            "element_type": f"scenic_{shape}",
            "x": x,
            "y": y,
            "fill": hex_color,
        }
        canvas_elements.append(element)

        logger.info(f"Bob painting: {shape} at ({x},{y}) size={size} color={color} [id={element_id}]")
        await rtvi.send_server_message({
            "type": "draw_shape",
            "id": element_id,
            "shape": shape,
            "color": hex_color,
            "color_name": color,
            "x": x,
            "y": y,
            "size": size,
        })
        await params.result_callback(
            f"Painted a {shape} using {color.replace('_', ' ').title()} (id={element_id})."
        )

    async def handle_add_element(params: FunctionCallParams):
        element_type: str = params.arguments.get("element_type", "rect")
        x: float = params.arguments.get("x", 50)
        y: float = params.arguments.get("y", 50)
        fill_raw: str = params.arguments.get("fill", "sap_green")
        stroke_raw: str = params.arguments.get("stroke", "")
        fill = resolve_color(fill_raw)
        stroke = resolve_color(stroke_raw) if stroke_raw else ""

        element_id = _next_element_id()
        element: CanvasElement = {
            "id": element_id,
            "element_type": element_type,
            "x": x,
            "y": y,
            "fill": fill,
            "stroke": stroke,
            "stroke_width": params.arguments.get("stroke_width", 0),
            "opacity": params.arguments.get("opacity", 1.0),
        }

        # Type-specific properties
        if element_type == "rect":
            element["width"] = params.arguments.get("width", 10)
            element["height"] = params.arguments.get("height", 10)
        elif element_type == "circle":
            element["radius"] = params.arguments.get("radius", 5)
        elif element_type == "ellipse":
            element["rx"] = params.arguments.get("width", 10) / 2
            element["ry"] = params.arguments.get("height", 5) / 2
        elif element_type == "line":
            element["x2"] = params.arguments.get("x2", x)
            element["y2"] = params.arguments.get("y2", y)
        elif element_type == "polygon":
            element["points"] = params.arguments.get("points", [[x, y]])
        elif element_type == "text":
            element["text"] = params.arguments.get("text", "")
            element["font_size"] = params.arguments.get("font_size", 5)

        canvas_elements.append(element)

        logger.info(f"Added element: {element_type} at ({x},{y}) [id={element_id}]")
        await rtvi.send_server_message({
            "type": "add_element",
            "element": element,
        })
        await params.result_callback(
            f"Added {element_type} element (id={element_id}) at position ({x}, {y})."
        )

    async def handle_remove_element(params: FunctionCallParams):
        element_id: str = params.arguments.get("element_id", "")
        removed = False
        for i, el in enumerate(canvas_elements):
            if el.get("id") == element_id:
                canvas_elements.pop(i)
                removed = True
                break

        if not removed:
            await params.result_callback(f"Element '{element_id}' not found on canvas.")
            return

        logger.info(f"Removed element: {element_id}, triggering full redraw")
        # Send full redraw: background + all remaining elements
        await rtvi.send_server_message({
            "type": "full_redraw",
            "background": background_state,
            "elements": canvas_elements,
        })
        await params.result_callback(
            f"Removed element '{element_id}'. Canvas redrawn with {len(canvas_elements)} remaining elements."
        )

    async def handle_list_elements(params: FunctionCallParams):
        if not canvas_elements:
            await params.result_callback("The canvas is empty — no tracked elements yet.")
            return

        summary_parts: list[str] = []
        for el in canvas_elements:
            el_id = el.get("id", "?")
            el_type = el.get("element_type", "?")
            el_x = el.get("x", 0)
            el_y = el.get("y", 0)
            summary_parts.append(f"  - {el_id}: {el_type} at ({el_x}, {el_y})")

        summary = f"Canvas has {len(canvas_elements)} elements:\n" + "\n".join(summary_parts)
        logger.info(f"Listed {len(canvas_elements)} elements")
        await params.result_callback(summary)

    async def handle_bobrossify(params: FunctionCallParams):
        intensity: str = params.arguments.get("intensity", "medium")
        logger.info(f"Applying Bob Ross painterly effect: intensity={intensity}")
        await rtvi.send_server_message({
            "type": "bobrossify",
            "intensity": intensity,
        })
        await params.result_callback(
            f"Applied the Bob Ross magic touch ({intensity} intensity). "
            "Now that's a happy little painting!"
        )

    def _describe_position(x: float, y: float) -> str:
        """Convert percentage coordinates to a natural language position."""
        h = "left" if x < 33 else "center" if x < 67 else "right"
        v = "upper" if y < 33 else "middle" if y < 67 else "lower"
        return f"{v}-{h}"

    def _build_canvas_summary() -> str:
        """Build a natural language description of the current canvas state."""
        parts: list[str] = []

        # Background
        if background_state.get("color_top") and background_state.get("color_bottom"):
            parts.append(
                f"Background gradient from {background_state['color_top']} (top) "
                f"to {background_state['color_bottom']} (bottom)."
            )

        # Elements
        for el in canvas_elements:
            el_type = el.get("element_type", "unknown")
            x = el.get("x", 50)
            y = el.get("y", 50)
            pos = _describe_position(x, y)
            color = el.get("fill", "")

            if el_type.startswith("scenic_"):
                shape_name = el_type.replace("scenic_", "")
                parts.append(f"A {shape_name} in the {pos} area (color: {color}).")
            else:
                parts.append(f"A {el_type} shape in the {pos} area (color: {color}).")

        if not parts:
            return "The canvas is mostly empty."
        return " ".join(parts)

    async def handle_generate_painting(params: FunctionCallParams):
        description: str = params.arguments.get("description", "a Bob Ross landscape")
        canvas_summary = _build_canvas_summary()

        prompt = (
            "Create a realistic Bob Ross-style oil painting using wet-on-wet technique. "
            f"Scene: {description}. "
            f"Canvas elements: {canvas_summary} "
            "Style: soft blended colors, happy little trees, dramatic lighting, "
            "thick impasto brush strokes, oil on canvas texture, warm tones, "
            "signature Bob Ross wet-on-wet oil painting look from 'The Joy of Painting'."
        )

        logger.info(f"Generating painting with prompt: {prompt[:200]}...")

        # Let the frontend know we're generating
        await rtvi.send_server_message({"type": "generating_painting"})

        try:
            openai_client = AsyncOpenAI()
            result = await openai_client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                n=1,
                size="1024x1024",
                quality="high",
                response_format="b64_json",
            )

            # gpt-image-1 returns base64 in result.data[0].b64_json
            image_b64 = result.data[0].b64_json
            if not image_b64:
                # Fallback: if b64_json is None, try URL (shouldn't happen with gpt-image-1)
                await params.result_callback(
                    "Hmm, looks like we had a little accident with that one. Let's try again later."
                )
                return

            logger.info(f"Painting generated successfully ({len(image_b64)} chars base64)")
            await rtvi.send_server_message({
                "type": "generated_painting",
                "image": image_b64,
            })
            await params.result_callback(
                "And there it is, your very own masterpiece! "
                "Just look at that. I knew you could do it."
            )
        except Exception as e:
            logger.error(f"Failed to generate painting: {e}")
            await params.result_callback(
                "Well, looks like we had a happy little accident with the image generation. "
                "But that's okay — every painting is already a masterpiece in its own way."
            )

    async def handle_set_color(params: FunctionCallParams):
        color_name: str = params.arguments.get("color_name", "titanium_white")
        hex_color = BOB_ROSS_COLORS.get(color_name, "#FAFAFA")
        logger.info(f"Bob set brush color to {color_name} ({hex_color})")
        await rtvi.send_server_message({
            "type": "set_color",
            "color": hex_color,
            "color_name": color_name,
        })
        await params.result_callback(f"Brush color changed to {color_name.replace('_', ' ').title()}.")

    async def handle_set_background(params: FunctionCallParams):
        color_top: str = params.arguments.get("color_top", "#1a0533")
        color_bottom: str = params.arguments.get("color_bottom", "#ff6b35")
        background_state["color_top"] = color_top
        background_state["color_bottom"] = color_bottom
        logger.info(f"Bob set background: {color_top} → {color_bottom}")
        await rtvi.send_server_message({
            "type": "set_background",
            "color_top": color_top,
            "color_bottom": color_bottom,
        })
        await params.result_callback("Background gradient has been laid down.")

    async def handle_clear_canvas(params: FunctionCallParams):
        canvas_elements.clear()
        background_state.clear()
        logger.info("Bob cleared the canvas")
        await rtvi.send_server_message({"type": "clear_canvas"})
        await params.result_callback("Canvas cleared — a brand new world awaits.")

    llm.register_function("draw_shape", handle_draw_shape)
    llm.register_function("add_element", handle_add_element)
    llm.register_function("remove_element", handle_remove_element)
    llm.register_function("list_elements", handle_list_elements)
    llm.register_function("bobrossify", handle_bobrossify)
    llm.register_function("generate_painting", handle_generate_painting)
    llm.register_function("set_color", handle_set_color)
    llm.register_function("set_background", handle_set_background)
    llm.register_function("clear_canvas", handle_clear_canvas)

    pipeline = Pipeline(
        [
            transport.input(),
            rtvi,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    rtvi_observer = RTVIObserver(rtvi)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True),
        observers=[rtvi_observer],
    )

    # Register AFTER task is created so closure captures it
    @rtvi.event_handler("on_client_message")
    async def on_client_message(processor, message):
        try:
            logger.info(f"Client message: type={message.type}, data={message.data}")
            if message.type == "interrupt":
                logger.info("Client requested interruption (spacebar)")
                await task.queue_frame(InterruptionFrame())
                return
            elif message.type == "stroke":
                # User painted something on the canvas
                data = message.data if isinstance(message.data, dict) else {}
                color = data.get("color", "unknown")
                await task.queue_frames(
                    [
                        LLMMessagesAppendFrame(
                            messages=[
                                {
                                    "role": "user",
                                    "content": (
                                        f"[The user just painted a freehand stroke on the canvas "
                                        f"using {color}. Comment on it briefly and encouragingly, "
                                        f"like Bob Ross would.]"
                                    ),
                                }
                            ],
                            run_llm=True,
                        )
                    ]
                )
            elif message.type == "color_pick":
                data = message.data if isinstance(message.data, dict) else {}
                color_name = data.get("color_name", "titanium_white")
                await task.queue_frames(
                    [
                        LLMMessagesAppendFrame(
                            messages=[
                                {
                                    "role": "user",
                                    "content": (
                                        f"[The user just picked {color_name.replace('_', ' ').title()} "
                                        f"from the color palette. Briefly acknowledge the color choice "
                                        f"in Bob Ross's style.]"
                                    ),
                                }
                            ],
                            run_llm=True,
                        )
                    ]
                )
        except Exception as e:
            logger.error(f"Error handling client message: {e}")

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        nonlocal client_participant_id
        client_participant_id = participant["id"]
        await transport.capture_participant_transcription(client_participant_id)
        logger.info(f"First participant joined: {client_participant_id}")

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        participant_id = participant["id"]
        logger.info(f"Participant left: {participant_id} (reason={reason})")
        if client_participant_id and participant_id != client_participant_id:
            logger.info(
                f"Ignoring participant departure for non-client participant {participant_id}"
            )
            return
        await task.queue_frame(EndFrame())

    runner = PipelineRunner()
    await runner.run(task)
