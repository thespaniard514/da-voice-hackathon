# Pipecat Voice Agent: Architecture & Reference

This doc covers how the voice agent works end-to-end and how to build new interactions between the frontend and backend.

## Project: Bob Ross Painting Buddy

A voice AI painting companion where "Bob Ross" guides users through landscape painting on a shared HTML5 canvas. The bot speaks in Bob Ross's signature soothing style and can programmatically paint shapes on the canvas, while users can freehand paint and talk back.

### Key Concept
- **Voice-first**: User talks via microphone, Bob responds with TTS (shimmer voice at 0.9x speed)
- **Shared canvas**: Both user (freehand drawing) and bot (tool-called shapes) paint on the same HTML5 canvas
- **Bidirectional sync**: Bot sends `draw_shape`/`set_color`/`set_background`/`clear_canvas` via RTVI; user sends `stroke`/`color_pick` events back

### Bot Tools
| Tool | Purpose | Server Message |
|------|---------|----------------|
| `draw_shape(shape, color, x, y, size)` | Paint trees, mountains, clouds, etc. | `{type: "draw_shape", ...}` |
| `set_color(color_name)` | Change user's brush color | `{type: "set_color", ...}` |
| `set_background(color_top, color_bottom)` | Gradient sky/base layer | `{type: "set_background", ...}` |
| `clear_canvas()` | Start fresh | `{type: "clear_canvas"}` |

### Client Events (user → bot)
| Event | When | Effect |
|-------|------|--------|
| `stroke` | User finishes a freehand stroke | Bob comments encouragingly |
| `color_pick` | User clicks a palette swatch | Bob acknowledges the color choice |

### Bob Ross Color Palette
Sap Green, Van Dyke Brown, Titanium White, Phthalo Blue, Alizarin Crimson, Cadmium Yellow, Bright Red, Prussian Blue, Indian Yellow, Midnight Black

### Canvas Shape Types
`tree`, `mountain`, `cloud`, `bush`, `lake`, `cabin`, `sun`, `path`

---

## Versions

| Component | Package | Version |
|-----------|---------|---------|
| Backend | `pipecat-ai[daily,openai,silero]` | 0.0.106 |
| Frontend | `@pipecat-ai/client-js` | 1.6.1 |
| Frontend | `@pipecat-ai/client-react` | 1.2.0 |
| Frontend | `@pipecat-ai/daily-transport` | 1.6.0 |

## How the Voice Pipeline Works

```
[Browser] <-- WebRTC (audio + data) --> [Daily.co Room] <-- WebRTC --> [Pipecat Bot]
    |                                                                      |
    +------------ POST /api/connect ---------> [FastAPI] -----------------+
```

### Connection Lifecycle

1. User clicks "Start Painting" → frontend calls `client.startBotAndConnect({ endpoint: "/api/connect" })`
2. Next.js proxies to Python backend (`POST /api/connect`)
3. Backend creates a Daily room + tokens, spawns bot in background task
4. Both client and bot join the same Daily room via WebRTC
5. Audio flows bidirectionally; JSON messages flow over the RTVI data channel

### The Pipeline (backend)

Frames flow through processors in order:

```python
pipeline = Pipeline([
    transport.input(),           # 1. Receive WebRTC audio
    rtvi,                        # 2. Handle RTVI JSON messages
    context_aggregator.user(),   # 3. Collect user speech into context
    llm,                         # 4. LLM generates text response
    tts,                         # 5. TTS converts text to audio
    transport.output(),          # 6. Send audio back via WebRTC
    context_aggregator.assistant()  # 7. Save assistant response to context
])
```

## Key Import Paths (Pipecat 0.0.106)

These changed from earlier versions. The old paths (`pipecat.services.openai`, `pipecat.transports.services.daily`, `pipecat.vad.silero`) are deprecated.

```python
# Transport
from pipecat.transports.daily.transport import DailyTransport, DailyParams

# LLM & TTS (use Settings objects, not bare kwargs)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.tts import OpenAITTSService

# VAD (moved to audio.vad)
from pipecat.audio.vad.silero import SileroVADAnalyzer

# Context (use LLMContext, NOT OpenAILLMContext)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)

# RTVI messaging
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor, RTVIObserver

# Frames
from pipecat.frames.frames import EndFrame, LLMMessagesAppendFrame

# Tool calling
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

# Pipeline
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
```

## Service Initialization

Settings are now passed via `Settings` objects (old kwargs like `model=` and `voice=` are deprecated):

```python
llm = OpenAILLMService(
    api_key=os.getenv("OPENAI_API_KEY"),
    settings=OpenAILLMService.Settings(model="gpt-4o-mini"),
)

tts = OpenAITTSService(
    api_key=os.getenv("OPENAI_API_KEY"),
    settings=OpenAITTSService.Settings(voice="shimmer", speed=0.9),
)
```

## VAD Configuration

VAD is no longer on `DailyParams`. It goes on the user aggregator:

```python
# NOT this (deprecated):
# DailyParams(vad_enabled=True, vad_analyzer=SileroVADAnalyzer())

# DO this:
context_aggregator = LLMContextAggregatorPair(
    context,
    user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(),
    ),
)
```

## PipelineTask Setup

`PipelineParams` must be passed as keyword arg. RTVIObserver is required when RTVIProcessor is in the pipeline:

```python
rtvi_observer = RTVIObserver(rtvi)

task = PipelineTask(
    pipeline,
    params=PipelineParams(allow_interruptions=True),  # keyword-only!
    observers=[rtvi_observer],
)
```

---

## Building New Interactions

### Pattern A: Client → Server (frontend sends data to backend)

**Frontend** — use `client.sendClientMessage(type, data)`:

```tsx
const client = usePipecatClient();
client?.sendClientMessage("my_event_type", { key: "value" });
```

**Backend** — register an `on_client_message` handler on the RTVIProcessor. Must be registered AFTER `task` is created:

```python
@rtvi.event_handler("on_client_message")
async def on_client_message(processor, message):
    # message.type = "my_event_type" (the first arg from sendClientMessage)
    # message.data = {"key": "value"} (the second arg)
    if message.type == "my_event_type":
        value = message.data.get("key")
        # do something with it
```

Available server-side RTVI events:
- `on_bot_started` — bot pipeline started
- `on_client_ready` — client connected and ready
- `on_client_message` — client sent a message via `sendClientMessage`

### Pattern B: Server → Client (backend pushes data to frontend)

**Backend** — use `rtvi.send_server_message(data)`:

```python
await rtvi.send_server_message({"type": "my_update", "payload": 123})
```

**Frontend** — listen with `useRTVIClientEvent("serverMessage", callback)`:

```tsx
useRTVIClientEvent(
    "serverMessage" as any,
    useCallback((msg: any) => {
        const data = msg?.data ?? msg;
        if (data?.type === "my_update") {
            // data.payload === 123
        }
    }, [])
);
```

### Pattern C: Triggering the Bot to Speak

To inject a message into the LLM context AND trigger a spoken response:

```python
await task.queue_frames([
    LLMMessagesAppendFrame(
        messages=[{"role": "user", "content": "Some injected message"}],
        run_llm=True,  # THIS triggers LLM completion
    )
])
```

**Critical**: `run_llm=True` is what makes the LLM actually generate a response. Without it, the message is just appended to context silently.

**Critical**: `task.queue_frames()` pushes from the START of the pipeline (downstream). This means the frame traverses the full pipeline including the user aggregator → LLM → TTS → transport output. Do NOT try to push frames directly into `llm.push_frame()` — it bypasses the aggregators and breaks context tracking.

**Wrong approaches** (do not use):
- `LLMFullResponseStartFrame` — this is an OUTPUT signal the LLM emits, not an input trigger
- `llm.push_frame(...)` — bypasses aggregators
- `context.add_message(...)` alone — updates context but doesn't trigger generation

### Pattern D: LLM Tool Calling (bot changes something)

Define tools with `ToolsSchema` + `FunctionSchema`:

```python
tools = ToolsSchema(
    standard_tools=[
        FunctionSchema(
            name="my_tool",
            description="What this tool does",
            properties={
                "param1": {"type": "string", "description": "..."},
            },
            required=["param1"],
        )
    ]
)

context = LLMContext(messages, tools)
```

Register the handler (uses single `FunctionCallParams` arg):

```python
async def handle_my_tool(params: FunctionCallParams):
    value = params.arguments.get("param1")
    # params.function_name — name of the tool
    # params.tool_call_id — unique call ID
    # params.arguments — dict of arguments
    # params.llm — the LLM service instance
    # params.context — the LLM context
    # params.result_callback — async callable to return result

    # Send result to frontend via RTVI
    await rtvi.send_server_message({"type": "tool_result", "value": value})

    # Return result to LLM (it will speak this)
    await params.result_callback(f"Done: {value}")

llm.register_function("my_tool", handle_my_tool)
```

## Frontend SDK Reference

### Key React Hooks

```tsx
import {
    PipecatClientProvider,
    PipecatClientAudio,       // REQUIRED — renders the <audio> element
    useRTVIClientEvent,       // listen for RTVI events
    usePipecatClient,         // get the PipecatClient instance
    usePipecatClientTransportState,  // "disconnected" | "connecting" | "connected" | "ready" | ...
} from "@pipecat-ai/client-react";
```

### Available Frontend Events (RTVIEvent)

Voice events:
- `userTranscript` — user speech transcribed (has `.text` and `.final`)
- `botTranscript` — bot speech transcribed
- `botStartedSpeaking` / `botStoppedSpeaking`
- `userStartedSpeaking` / `userStoppedSpeaking`

Connection events:
- `connected` / `disconnected`
- `botReady` — bot is connected and ready
- `transportStateChanged`

Data events:
- `serverMessage` — server pushed a message via `send_server_message`

### Client Initialization

```tsx
const [client] = useState(() =>
    new PipecatClient({
        transport: new DailyTransport(),
        enableMic: true,
    })
);

// Connect (must be from a click handler for audio context)
await client.startBotAndConnect({ endpoint: "/api/connect" });

// Send data to backend
client.sendClientMessage("event_type", { key: "value" });

// Disconnect
await client.disconnect();
```

## Where to Find References

- **Pipecat Python docs**: https://docs.pipecat.ai
- **RTVI framework**: https://docs.pipecat.ai/server/frameworks/rtvi
- **Daily transport**: https://docs.pipecat.ai/server/services/transport/daily
- **Installed Python source** (authoritative for exact signatures): `docker run --rm da-voice-hackathon-server python -c "import inspect; from pipecat.MODULE import CLASS; print(inspect.getsource(CLASS))"`
- **Frontend SDK types**: `ux-web/node_modules/@pipecat-ai/client-js/dist/index.d.ts`
- **Frontend React hooks**: `ux-web/node_modules/@pipecat-ai/client-react/dist/index.d.ts`
