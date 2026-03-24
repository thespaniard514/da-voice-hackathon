# Generate Realistic Bob Ross Painting from Canvas

**Date:** 2026-03-23
**Status:** Approved

## Summary

Add a voice-triggered tool that generates a realistic Bob Ross-style oil painting from the current canvas state using OpenAI's `gpt-image-1` model. The generated image fades in over the canvas as a dramatic reveal.

## Motivation

The canvas currently shows procedural shapes (triangles for mountains, circles for clouds, etc.). Users want to see what their painting would look like as a realistic Bob Ross oil painting at the end of a session.

## Design

### New Tool: `generate_painting`

**LLM Tool Definition:**

```python
{
    "type": "function",
    "function": {
        "name": "generate_painting",
        "description": "Generate a realistic Bob Ross-style oil painting based on the current canvas. Call this when the user wants to see what their painting would really look like.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "A rich, detailed description of the painting scene, mood, lighting, and atmosphere based on the conversation."
                }
            },
            "required": ["description"]
        }
    }
}
```

### Backend Handler (`bot.py`)

1. Build a structured canvas summary from `canvas_elements` and `background_state`:
   - List each element with type, position (as spatial description like "upper-left"), color, and size
   - Include background gradient colors
2. Compose image generation prompt:
   ```
   Create a realistic Bob Ross-style oil painting using wet-on-wet technique.
   Scene: {LLM description}
   Canvas elements: {structured summary}
   Style: soft blended colors, happy trees, dramatic lighting, thick impasto brush strokes, oil on canvas texture.
   ```
3. Call OpenAI images API:
   ```python
   from openai import AsyncOpenAI
   client = AsyncOpenAI()
   result = await client.images.generate(
       model="gpt-image-1",
       prompt=composed_prompt,
       n=1,
       size="1024x1024",
       quality="high"
   )
   ```
4. Send base64 image to frontend:
   ```python
   await rtvi.send_server_message({
       "type": "generated_painting",
       "image": result.data[0].b64_json
   })
   ```
5. Return spoken response to LLM: `"There it is! Your very own masterpiece."`

### Frontend Changes (`voice-shell.tsx`)

**New State:**
- `generatedImage: string | null` — base64 image data
- `showGenerated: boolean` — controls fade visibility

**New UI:**
- `<img>` element absolutely positioned over the canvas
- CSS transition: `opacity 1.5s ease-in-out`
- When `generated_painting` message received: set `generatedImage`, then trigger `showGenerated = true`
- "Back to canvas" button overlaid on the image (fades in after image appears)
- Clicking "Back to canvas" sets `showGenerated = false` (fades back to canvas)

**Server Message Handler:**
```tsx
if (data?.type === "generated_painting") {
    setGeneratedImage(`data:image/png;base64,${data.image}`);
    // Small delay to ensure image is loaded before fade
    setTimeout(() => setShowGenerated(true), 100);
}
```

### Data Flow

```
User voice: "Let's see the final painting"
  -> LLM decides to call generate_painting(description="...")
  -> Bot handler:
     1. Reads canvas_elements + background_state
     2. Builds spatial description of canvas
     3. Composes prompt = style prefix + LLM description + canvas summary
     4. Calls OpenAI gpt-image-1 (b64_json response format)
     5. Sends {type: "generated_painting", image: base64} to frontend
     6. Returns "There it is!" to LLM for speech
  -> Frontend:
     1. Receives server message
     2. Sets image src
     3. Fades in over canvas (1.5s transition)
     4. Shows "Back to canvas" button
```

### Canvas State to Prompt Mapping

Helper function `describe_canvas_state()` converts retained-mode elements to natural language:

| Element | Prompt Fragment |
|---------|----------------|
| `scenic_tree` at (20, 60) | "a tree on the left side of the middle ground" |
| `scenic_mountain` at (50, 20) | "a mountain in the center background" |
| `scenic_cloud` at (70, 10) | "clouds in the upper right sky" |
| `scenic_lake` at (50, 70) | "a lake in the foreground" |
| `scenic_cabin` at (60, 50) | "a small cabin on the right" |
| `scenic_sun` at (80, 15) | "sun in the upper right" |
| Background `#003153` to `#E3A857` | "a sky transitioning from deep blue to golden amber" |

Position mapping (x: 0-33 = left, 34-66 = center, 67-100 = right; y: 0-33 = upper/background, 34-66 = middle, 67-100 = lower/foreground).

### Error Handling

- If the OpenAI API call fails, the bot says "Hmm, looks like we had a little accident with that one. Let's try again later." and returns gracefully.
- If canvas is empty, the bot should still generate based on its description (the LLM's creative interpretation).

### System Prompt Update

Add to the existing system prompt:
```
When the user asks to see the "real" painting, final result, or what it would really look like, call the generate_painting tool with a rich description of the scene.
```

## Out of Scope

- Multiple image generation styles (only Bob Ross oil painting)
- Saving/downloading the generated image (future enhancement)
- Image-to-image generation (using canvas as visual input)
- Streaming/progressive image loading

## Dependencies

- `openai` Python package (already installed for LLM)
- `OPENAI_API_KEY` environment variable (already configured)
- OpenAI `gpt-image-1` model access
