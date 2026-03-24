import asyncio
import json
import os

from pipecat.frames.frames import EndFrame, LLMMessagesAppendFrame
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
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from loguru import logger

# Bob Ross color palette
BOB_ROSS_COLORS = {
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

# Current canvas state
current_color = "titanium_white"


async def run_bot(room_url: str, token: str):
    global current_color
    current_color = "titanium_white"

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
        settings=OpenAILLMService.Settings(model="gpt-4o-mini"),
    )

    tts = OpenAITTSService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAITTSService.Settings(voice="shimmer", speed=0.9),
    )

    tools = ToolsSchema(
        standard_tools=[
            FunctionSchema(
                name="draw_shape",
                description=(
                    "Draw a shape on the shared painting canvas. Use this to paint elements "
                    "like trees, mountains, clouds, bushes, a lake, a cabin, or the sun. "
                    "Coordinates are percentages of canvas size (0-100)."
                ),
                properties={
                    "shape": {
                        "type": "string",
                        "enum": ["tree", "mountain", "cloud", "bush", "lake", "cabin", "sun", "path"],
                        "description": "The type of shape/element to paint",
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
                description="Clear the entire canvas to start fresh with a brand new painting.",
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
                "You are co-painting with the user on a shared canvas. You can:\n"
                "1. Paint shapes on the canvas using draw_shape (trees, mountains, clouds, etc.)\n"
                "2. Change the user's brush color using set_color\n"
                "3. Set the background/sky using set_background\n"
                "4. Clear the canvas to start fresh\n\n"
                "Start by welcoming the user warmly and suggesting you begin with a nice sky. "
                "As you paint, narrate what you're doing, just like on the TV show. "
                "When the user paints something, comment on it encouragingly."
            ),
        }
    ]

    context = LLMContext(messages, tools)
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # --- Tool handlers ---

    async def handle_draw_shape(params: FunctionCallParams):
        shape = params.arguments.get("shape", "tree")
        color = params.arguments.get("color", "sap_green")
        x = params.arguments.get("x", 50)
        y = params.arguments.get("y", 50)
        size = params.arguments.get("size", 15)
        hex_color = BOB_ROSS_COLORS.get(color, "#0A3410")
        logger.info(f"Bob painting: {shape} at ({x},{y}) size={size} color={color}")
        await rtvi.send_server_message({
            "type": "draw_shape",
            "shape": shape,
            "color": hex_color,
            "color_name": color,
            "x": x,
            "y": y,
            "size": size,
        })
        await params.result_callback(f"Painted a {shape} using {color.replace('_', ' ').title()}.")

    async def handle_set_color(params: FunctionCallParams):
        global current_color
        color_name = params.arguments.get("color_name", "titanium_white")
        hex_color = BOB_ROSS_COLORS.get(color_name, "#FAFAFA")
        current_color = color_name
        logger.info(f"Bob set brush color to {color_name} ({hex_color})")
        await rtvi.send_server_message({
            "type": "set_color",
            "color": hex_color,
            "color_name": color_name,
        })
        await params.result_callback(f"Brush color changed to {color_name.replace('_', ' ').title()}.")

    async def handle_set_background(params: FunctionCallParams):
        color_top = params.arguments.get("color_top", "#1a0533")
        color_bottom = params.arguments.get("color_bottom", "#ff6b35")
        logger.info(f"Bob set background: {color_top} → {color_bottom}")
        await rtvi.send_server_message({
            "type": "set_background",
            "color_top": color_top,
            "color_bottom": color_bottom,
        })
        await params.result_callback("Background gradient has been laid down.")

    async def handle_clear_canvas(params: FunctionCallParams):
        logger.info("Bob cleared the canvas")
        await rtvi.send_server_message({"type": "clear_canvas"})
        await params.result_callback("Canvas cleared — a brand new world awaits.")

    llm.register_function("draw_shape", handle_draw_shape)
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
            if message.type == "stroke":
                # User painted something on the canvas
                data = message.data if isinstance(message.data, dict) else {}
                color = data.get("color", "unknown")
                bounds = data.get("bounds", "somewhere")
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
        await transport.capture_participant_transcription(participant["id"])
        logger.info(f"First participant joined: {participant['id']}")

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left: {participant['id']}")
        await task.queue_frame(EndFrame())

    runner = PipelineRunner()
    await runner.run(task)
