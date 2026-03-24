"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { PipecatClient } from "@pipecat-ai/client-js";
import {
  PipecatClientProvider,
  PipecatClientAudio,
  useRTVIClientEvent,
  usePipecatClient,
} from "@pipecat-ai/client-react";
import { DailyTransport } from "@pipecat-ai/daily-transport";

// Bob Ross color palette
const COLORS: Record<string, { hex: string; label: string }> = {
  sap_green: { hex: "#0A3410", label: "Sap Green" },
  van_dyke_brown: { hex: "#462806", label: "Van Dyke Brown" },
  titanium_white: { hex: "#FAFAFA", label: "Titanium White" },
  phthalo_blue: { hex: "#000F89", label: "Phthalo Blue" },
  alizarin_crimson: { hex: "#E32636", label: "Alizarin Crimson" },
  cadmium_yellow: { hex: "#FFF600", label: "Cadmium Yellow" },
  bright_red: { hex: "#FF0800", label: "Bright Red" },
  prussian_blue: { hex: "#003153", label: "Prussian Blue" },
  indian_yellow: { hex: "#E3A857", label: "Indian Yellow" },
  midnight_black: { hex: "#0A0A0A", label: "Midnight Black" },
};

// ---- Canvas drawing helpers ----

function drawTree(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  color: string
) {
  const trunkW = size * 0.1;
  const trunkH = size * 0.35;
  // Trunk
  ctx.fillStyle = "#462806";
  ctx.fillRect(cx - trunkW / 2, cy - trunkH, trunkW, trunkH);
  // Foliage (layered triangles)
  ctx.fillStyle = color;
  for (let i = 0; i < 3; i++) {
    const layerSize = size * (0.7 - i * 0.15);
    const layerY = cy - trunkH - i * size * 0.2;
    ctx.beginPath();
    ctx.moveTo(cx - layerSize / 2, layerY);
    ctx.lineTo(cx + layerSize / 2, layerY);
    ctx.lineTo(cx, layerY - layerSize * 0.7);
    ctx.closePath();
    ctx.fill();
  }
}

function drawMountain(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  color: string
) {
  const w = size * 1.5;
  const h = size * 1.0;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(cx - w / 2, cy);
  ctx.lineTo(cx, cy - h);
  ctx.lineTo(cx + w / 2, cy);
  ctx.closePath();
  ctx.fill();
  // Snow cap
  ctx.fillStyle = "#FAFAFA";
  ctx.beginPath();
  ctx.moveTo(cx - w * 0.1, cy - h * 0.75);
  ctx.lineTo(cx, cy - h);
  ctx.lineTo(cx + w * 0.1, cy - h * 0.75);
  ctx.closePath();
  ctx.fill();
}

function drawCloud(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  color: string
) {
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.8;
  const r = size * 0.25;
  for (const [dx, dy, s] of [
    [0, 0, r],
    [-r, r * 0.2, r * 0.8],
    [r, r * 0.1, r * 0.9],
    [-r * 0.5, -r * 0.3, r * 0.7],
    [r * 0.5, -r * 0.2, r * 0.75],
  ]) {
    ctx.beginPath();
    ctx.arc(cx + dx, cy + dy, s, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawBush(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  color: string
) {
  ctx.fillStyle = color;
  const r = size * 0.3;
  for (const [dx, dy, s] of [
    [0, 0, r],
    [-r * 0.7, 0, r * 0.7],
    [r * 0.7, 0, r * 0.7],
  ]) {
    ctx.beginPath();
    ctx.arc(cx + dx, cy + dy, s, Math.PI, 0);
    ctx.fill();
  }
}

function drawLake(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  color: string
) {
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.6;
  ctx.beginPath();
  ctx.ellipse(cx, cy, size * 0.8, size * 0.3, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
}

function drawSun(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  color: string
) {
  const r = size * 0.3;
  // Glow
  const grad = ctx.createRadialGradient(cx, cy, r * 0.5, cx, cy, r * 2);
  grad.addColorStop(0, color);
  grad.addColorStop(1, "transparent");
  ctx.fillStyle = grad;
  ctx.fillRect(cx - r * 2, cy - r * 2, r * 4, r * 4);
  // Core
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
}

function drawCabin(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  color: string
) {
  const w = size * 0.6;
  const h = size * 0.4;
  // Walls
  ctx.fillStyle = color;
  ctx.fillRect(cx - w / 2, cy - h, w, h);
  // Roof
  ctx.fillStyle = "#3C1414";
  ctx.beginPath();
  ctx.moveTo(cx - w * 0.65, cy - h);
  ctx.lineTo(cx, cy - h * 1.8);
  ctx.lineTo(cx + w * 0.65, cy - h);
  ctx.closePath();
  ctx.fill();
  // Door
  ctx.fillStyle = "#462806";
  ctx.fillRect(cx - w * 0.1, cy - h * 0.6, w * 0.2, h * 0.6);
}

const SHAPE_DRAWERS: Record<
  string,
  (
    ctx: CanvasRenderingContext2D,
    cx: number,
    cy: number,
    size: number,
    color: string
  ) => void
> = {
  tree: drawTree,
  mountain: drawMountain,
  cloud: drawCloud,
  bush: drawBush,
  lake: drawLake,
  sun: drawSun,
  cabin: drawCabin,
};

// ---- Components ----

function PaintCanvas({
  activeColor,
  brushSize,
  onStroke,
  canvasRef,
}: {
  activeColor: string;
  brushSize: number;
  onStroke: (color: string) => void;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
}) {
  const isDrawing = useRef(false);
  const lastPos = useRef<{ x: number; y: number } | null>(null);

  const getPos = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * canvas.width,
      y: ((e.clientY - rect.top) / rect.height) * canvas.height,
    };
  };

  const startDraw = (e: React.MouseEvent<HTMLCanvasElement>) => {
    isDrawing.current = true;
    lastPos.current = getPos(e);
  };

  const draw = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDrawing.current || !canvasRef.current) return;
    const ctx = canvasRef.current.getContext("2d");
    if (!ctx || !lastPos.current) return;
    const pos = getPos(e);
    ctx.strokeStyle = activeColor;
    ctx.lineWidth = brushSize;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(lastPos.current.x, lastPos.current.y);
    ctx.lineTo(pos.x, pos.y);
    ctx.stroke();
    lastPos.current = pos;
  };

  const endDraw = () => {
    if (isDrawing.current) {
      isDrawing.current = false;
      lastPos.current = null;
      onStroke(activeColor);
    }
  };

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem",
        position: "relative",
      }}
    >
      {/* Wood frame */}
      <div
        style={{
          padding: "12px",
          borderRadius: "4px",
          background:
            "linear-gradient(145deg, #5C3A1E 0%, #3E2712 50%, #5C3A1E 100%)",
          boxShadow:
            "0 12px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.08)",
          display: "flex",
          position: "relative",
        }}
      >
        <canvas
          ref={canvasRef}
          width={960}
          height={600}
          onMouseDown={startDraw}
          onMouseMove={draw}
          onMouseUp={endDraw}
          onMouseLeave={endDraw}
          style={{
            display: "block",
            width: "100%",
            maxWidth: "960px",
            height: "auto",
            cursor: "crosshair",
            borderRadius: "2px",
            background: "#F5F0E8",
          }}
        />
      </div>
    </div>
  );
}

function ColorPalette({
  activeColor,
  onColorChange,
}: {
  activeColor: string;
  onColorChange: (name: string, hex: string) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: "8px",
        justifyContent: "center",
        padding: "0.75rem 0",
      }}
    >
      {Object.entries(COLORS).map(([name, { hex, label }]) => (
        <button
          key={name}
          title={label}
          onClick={() => onColorChange(name, hex)}
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            border: "none",
            background: hex,
            cursor: "pointer",
            boxShadow:
              activeColor === name
                ? `0 0 0 3px #ffdd79, 0 0 12px ${hex}`
                : `0 2px 4px rgba(0,0,0,0.3)`,
            transform: activeColor === name ? "scale(1.15)" : "scale(1)",
            transition: "all 0.15s ease",
          }}
        />
      ))}
    </div>
  );
}

function BrushControls({
  brushSize,
  onBrushSizeChange,
}: {
  brushSize: number;
  onBrushSizeChange: (size: number) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        padding: "0.25rem 0",
      }}
    >
      <span
        style={{
          fontSize: "0.7rem",
          color: "#acabaa",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          minWidth: "3rem",
        }}
      >
        Brush
      </span>
      <input
        type="range"
        min={2}
        max={24}
        value={brushSize}
        onChange={(e) => onBrushSizeChange(Number(e.target.value))}
        style={{
          flex: 1,
          accentColor: "#ffdd79",
          height: "4px",
        }}
      />
      <div
        style={{
          width: brushSize,
          height: brushSize,
          borderRadius: "50%",
          background: "#e5beb5",
          minWidth: "4px",
        }}
      />
    </div>
  );
}

let msgCounter = 0;

function TranscriptDisplay() {
  const [messages, setMessages] = useState<
    { role: string; text: string; id: number }[]
  >([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useRTVIClientEvent(
    "userTranscript" as any,
    useCallback((data: any) => {
      if (data.final) {
        setMessages((prev) => [
          ...prev.slice(-29),
          { role: "user", text: data.text, id: ++msgCounter },
        ]);
      }
    }, [])
  );

  useRTVIClientEvent(
    "botTranscript" as any,
    useCallback((data: any) => {
      setMessages((prev) => [
        ...prev.slice(-29),
        { role: "bot", text: data.text, id: ++msgCounter },
      ]);
    }, [])
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div
      style={{
        flex: 1,
        overflowY: "auto",
        padding: "0.5rem 0",
      }}
    >
      {messages.map((m) => (
        <div
          key={m.id}
          style={{
            textAlign: m.role === "user" ? "right" : "left",
            margin: "0.4rem 0",
          }}
        >
          <span
            style={{
              display: "inline-block",
              padding: "0.4rem 0.8rem",
              borderRadius: "0.75rem",
              background:
                m.role === "user" ? "#37201a" : "rgba(255,221,121,0.1)",
              color: m.role === "user" ? "#e5beb5" : "#ffdd79",
              fontSize: "0.85rem",
              maxWidth: "85%",
              fontFamily: "'Be Vietnam Pro', system-ui, sans-serif",
            }}
          >
            {m.role === "bot" ? "🎨 " : "🎤 "}
            {m.text}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

function BobStatus({ isSpeaking }: { isSpeaking: boolean }) {
  return (
    <div
      style={{
        position: "absolute",
        top: "2.5rem",
        right: "2.5rem",
        background: "rgba(26,25,25,0.85)",
        backdropFilter: "blur(12px)",
        padding: "0.4rem 1rem",
        borderRadius: "2rem",
        fontSize: "0.8rem",
        color: "#ffdd79",
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        boxShadow: isSpeaking
          ? "0 0 20px rgba(255,221,121,0.2)"
          : "0 4px 12px rgba(0,0,0,0.3)",
        transition: "box-shadow 0.3s ease",
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: isSpeaking ? "#ffdd79" : "#484848",
          boxShadow: isSpeaking ? "0 0 8px #ffdd79" : "none",
          transition: "all 0.3s",
        }}
      />
      {isSpeaking ? "Bob is painting..." : "Listening..."}
    </div>
  );
}

function CanvasToolbar({
  onClear,
  brushSize,
}: {
  onClear: () => void;
  brushSize: number;
}) {
  return (
    <div
      style={{
        position: "absolute",
        bottom: "2.5rem",
        left: "50%",
        transform: "translateX(-50%)",
        background: "rgba(26,25,25,0.75)",
        backdropFilter: "blur(16px)",
        padding: "0.5rem 1.5rem",
        borderRadius: "2rem",
        display: "flex",
        gap: "1.25rem",
        alignItems: "center",
        boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
      }}
    >
      {[4, 10, 20].map((s) => (
        <div
          key={s}
          style={{
            width: s + 4,
            height: s + 4,
            borderRadius: "50%",
            background: brushSize === s ? "#ffdd79" : "#acabaa",
            opacity: brushSize === s ? 1 : 0.5,
            cursor: "pointer",
          }}
        />
      ))}
      <div
        style={{ width: 1, height: 20, background: "rgba(255,255,255,0.1)" }}
      />
      <button
        onClick={onClear}
        title="Clear canvas"
        style={{
          background: "transparent",
          border: "none",
          color: "#fe7453",
          cursor: "pointer",
          fontSize: "1rem",
          padding: "0.25rem",
        }}
      >
        ✕
      </button>
    </div>
  );
}

function ConnectedUI({
  activeColorName,
  activeColorHex,
  brushSize,
  isSpeaking,
  onColorChange,
  onBrushSizeChange,
  onStroke,
  onEnd,
  canvasRef,
}: {
  activeColorName: string;
  activeColorHex: string;
  brushSize: number;
  isSpeaking: boolean;
  onColorChange: (name: string, hex: string) => void;
  onBrushSizeChange: (size: number) => void;
  onStroke: (color: string) => void;
  onEnd: () => void;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
}) {
  const client = usePipecatClient();

  // Listen for server messages (bot painting on canvas)
  useRTVIClientEvent(
    "serverMessage" as any,
    useCallback(
      (msg: any) => {
        const data = msg?.data ?? msg;
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        if (data?.type === "draw_shape") {
          const { shape, color, x, y, size: pctSize } = data;
          const cx = (x / 100) * canvas.width;
          const cy = (y / 100) * canvas.height;
          const sz = (pctSize / 100) * Math.min(canvas.width, canvas.height);
          const drawer = SHAPE_DRAWERS[shape];
          if (drawer) drawer(ctx, cx, cy, sz, color);
        } else if (data?.type === "set_background") {
          const { color_top, color_bottom } = data;
          const grad = ctx.createLinearGradient(0, 0, 0, canvas.height);
          grad.addColorStop(0, color_top);
          grad.addColorStop(1, color_bottom);
          ctx.fillStyle = grad;
          ctx.fillRect(0, 0, canvas.width, canvas.height);
        } else if (data?.type === "set_color") {
          onColorChange(data.color_name, data.color);
        } else if (data?.type === "clear_canvas") {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          // Reset to canvas color
          ctx.fillStyle = "#F5F0E8";
          ctx.fillRect(0, 0, canvas.width, canvas.height);
        }
      },
      [canvasRef, onColorChange]
    )
  );

  const handleUserColorChange = useCallback(
    (name: string, hex: string) => {
      onColorChange(name, hex);
      try {
        client?.sendClientMessage("color_pick", { color_name: name });
      } catch (err) {
        console.error("Failed to send color pick:", err);
      }
    },
    [client, onColorChange]
  );

  const handleStroke = useCallback(
    (color: string) => {
      onStroke(color);
      try {
        client?.sendClientMessage("stroke", { color });
      } catch (err) {
        console.error("Failed to send stroke:", err);
      }
    },
    [client, onStroke]
  );

  return (
    <div style={{ display: "flex", width: "100%", height: "100vh" }}>
      {/* Left sidebar */}
      <div
        style={{
          width: 320,
          minWidth: 280,
          display: "flex",
          flexDirection: "column",
          padding: "1.5rem",
          background: "#131313",
          fontFamily: "'Be Vietnam Pro', system-ui, sans-serif",
        }}
      >
        <h2
          style={{
            fontSize: "1.1rem",
            fontWeight: 700,
            marginBottom: "0.15rem",
            color: "#ffdd79",
            fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
          }}
        >
          🎨 Bob Ross Painting Buddy
        </h2>
        <p style={{ color: "#acabaa", fontSize: "0.75rem", marginBottom: "1rem" }}>
          &quot;There are no mistakes, only happy accidents.&quot;
        </p>

        <div
          style={{
            fontSize: "0.65rem",
            color: "#767575",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: "0.3rem",
          }}
        >
          Colors
        </div>
        <ColorPalette
          activeColor={activeColorName}
          onColorChange={handleUserColorChange}
        />

        <BrushControls
          brushSize={brushSize}
          onBrushSizeChange={onBrushSizeChange}
        />

        <div
          style={{
            marginTop: "1rem",
            fontSize: "0.65rem",
            color: "#767575",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          Transcript
        </div>
        <TranscriptDisplay />

        <button
          onClick={onEnd}
          style={{
            marginTop: "auto",
            padding: "0.6rem 1rem",
            borderRadius: "0.5rem",
            border: "none",
            background: "#fe7453",
            color: "#fff",
            cursor: "pointer",
            fontSize: "0.85rem",
            fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
            fontWeight: 600,
          }}
        >
          End Session
        </button>
      </div>

      {/* Right pane: canvas */}
      <div style={{ flex: 1, position: "relative", background: "#0e0e0e" }}>
        <PaintCanvas
          activeColor={activeColorHex}
          brushSize={brushSize}
          onStroke={handleStroke}
          canvasRef={canvasRef}
        />
        <BobStatus isSpeaking={isSpeaking} />
        <CanvasToolbar
          onClear={() => {
            const canvas = canvasRef.current;
            if (!canvas) return;
            const ctx = canvas.getContext("2d");
            if (!ctx) return;
            ctx.fillStyle = "#F5F0E8";
            ctx.fillRect(0, 0, canvas.width, canvas.height);
          }}
          brushSize={brushSize}
        />
      </div>
    </div>
  );
}

export function VoiceShell() {
  const [client] = useState(
    () =>
      new PipecatClient({
        transport: new DailyTransport(),
        enableMic: true,
      })
  );
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [activeColorName, setActiveColorName] = useState("titanium_white");
  const [activeColorHex, setActiveColorHex] = useState("#FAFAFA");
  const [brushSize, setBrushSize] = useState(6);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Track bot speaking state
  useRTVIClientEvent(
    "botStartedSpeaking" as any,
    useCallback(() => setIsSpeaking(true), [])
  );
  useRTVIClientEvent(
    "botStoppedSpeaking" as any,
    useCallback(() => setIsSpeaking(false), [])
  );

  const handleColorChange = useCallback((name: string, hex: string) => {
    setActiveColorName(name);
    setActiveColorHex(hex);
  }, []);

  const startSession = async () => {
    setConnecting(true);
    try {
      await client.startBotAndConnect({
        endpoint: "/api/connect",
      });
      setConnected(true);
    } catch (err) {
      console.error("Connection failed:", err);
    } finally {
      setConnecting(false);
    }
  };

  const endSession = async () => {
    await client.disconnect();
    setConnected(false);
    setActiveColorName("titanium_white");
    setActiveColorHex("#FAFAFA");
    setBrushSize(6);
    setIsSpeaking(false);
  };

  return (
    <PipecatClientProvider client={client}>
      <PipecatClientAudio />
      {!connected ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            width: "100%",
            height: "100vh",
            background: "#0e0e0e",
            fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
          }}
        >
          <div style={{ fontSize: "4rem", marginBottom: "1rem" }}>🎨</div>
          <h1
            style={{
              fontSize: "2.5rem",
              marginBottom: "0.5rem",
              color: "#ffdd79",
              fontWeight: 800,
            }}
          >
            Bob Ross Painting Buddy
          </h1>
          <p
            style={{
              color: "#e5beb5",
              marginBottom: "0.5rem",
              fontStyle: "italic",
              fontFamily: "'Be Vietnam Pro', system-ui, sans-serif",
              fontSize: "1.1rem",
            }}
          >
            &quot;There are no mistakes, only happy little accidents.&quot;
          </p>
          <p
            style={{
              color: "#acabaa",
              marginBottom: "2.5rem",
              maxWidth: "28rem",
              textAlign: "center",
              lineHeight: 1.6,
              fontFamily: "'Be Vietnam Pro', system-ui, sans-serif",
              fontSize: "0.95rem",
            }}
          >
            Talk to Bob and paint together. He&apos;ll guide you through a
            landscape, suggest colors, and paint alongside you — all with your
            voice.
          </p>
          <button
            onClick={startSession}
            disabled={connecting}
            style={{
              padding: "1rem 2.5rem",
              fontSize: "1.2rem",
              fontWeight: 700,
              borderRadius: "0.75rem",
              border: "none",
              background: connecting
                ? "#484848"
                : "linear-gradient(135deg, #ffdd79, #e6c047)",
              color: "#3E2712",
              cursor: connecting ? "wait" : "pointer",
              boxShadow: connecting
                ? "none"
                : "0 4px 20px rgba(255,221,121,0.3)",
              transition: "all 0.2s ease",
            }}
          >
            {connecting ? "Setting up the easel..." : "Start Painting 🖌️"}
          </button>
          <p
            style={{
              color: "#767575",
              fontSize: "0.75rem",
              marginTop: "1rem",
            }}
          >
            Microphone access required
          </p>
        </div>
      ) : (
        <ConnectedUI
          activeColorName={activeColorName}
          activeColorHex={activeColorHex}
          brushSize={brushSize}
          isSpeaking={isSpeaking}
          onColorChange={handleColorChange}
          onBrushSizeChange={setBrushSize}
          onStroke={() => {}}
          onEnd={endSession}
          canvasRef={canvasRef}
        />
      )}
    </PipecatClientProvider>
  );
}
