import type { AgentEvent, ChatMessage, MessagePart } from "@/lib/agent-types";

/** Mensaje del asistente que se está generando (se rehace desde BD al terminar). */
export interface LiveState {
  message: ChatMessage;
  running: Set<string>;
  lastSeq: number;
  runId: number | null;
}

export function emptyLive(): LiveState {
  return {
    message: { id: "live", role: "assistant", content: null, parts: [] },
    running: new Set(),
    lastSeq: 0,
    runId: null,
  };
}

export function applyEvent(state: LiveState, event: AgentEvent): LiveState {
  const parts: MessagePart[] = [...state.message.parts];
  const running = new Set(state.running);
  switch (event.type) {
    case "TEXT_DELTA": {
      const last = parts[parts.length - 1];
      if (last && last.type === "text") parts[parts.length - 1] = { ...last, text: last.text + event.delta };
      else parts.push({ type: "text", text: event.delta });
      break;
    }
    case "TOOL_CALL_START":
      running.add(event.call_id);
      parts.push({ type: "tool", call_id: event.call_id, name: event.name, args: event.args, result: undefined });
      break;
    case "TOOL_CALL_RESULT": {
      running.delete(event.call_id);
      const index = parts.findIndex((part) => part.type === "tool" && part.call_id === event.call_id);
      const part = { type: "tool" as const, call_id: event.call_id, name: event.name, args: event.args, result: event.result };
      if (index >= 0) parts[index] = part;
      else parts.push(part);
      break;
    }
    case "SKILL_ACTIVATED":
      parts.push({ type: "skill", name: event.name });
      break;
    case "APPROVAL_REQUIRED":
      parts.push({ type: "approvals", items: event.approvals });
      break;
    default:
      break;
  }
  return {
    message: { ...state.message, parts },
    running,
    lastSeq: Math.max(state.lastSeq, event.seq),
    runId: event.run_id ?? state.runId,
  };
}
