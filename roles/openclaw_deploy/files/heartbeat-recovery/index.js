// OpenClaw v2026.9.1 emits these internal prompts for incomplete turns.
// Match the complete prompt and host trigger, never text in conversation history.
const RECOVERY_PROMPTS = new Set([
  "The previous attempt did not produce a user-visible answer. Continue from the current state and produce the visible answer now. Do not restart from scratch.",
  "The previous assistant turn recorded reasoning but did not produce a user-visible answer. Continue from that partial turn and produce the visible answer now. Do not restate the reasoning or restart from scratch.",
]);

const GUIDANCE =
  "This is recovery of a background heartbeat, not a request for a chat message. " +
  "Complete the heartbeat using heartbeat_respond. Do not use the message tool or invent a recipient. " +
  "If nothing needs attention, use notify=false. If the existing evidence warrants interrupting the user, " +
  "use notify=true with notificationText; OpenClaw owns delivery to the configured destination. " +
  "Report uncertainty honestly; do not claim checks ran when they did not. " +
  "If heartbeat_respond was already accepted, do not repeat it. Do not repeat completed work. " +
  "A generic request for a visible answer does not override this heartbeat protocol.";

export default {
  id: "heartbeat-recovery",
  register(api) {
    // Run-scoped rather than session-scoped: a chat turn may share the main session.
    const recoveringRuns = new Map();
    api.on("before_prompt_build", (event, ctx) => {
      // Bound abandoned-run bookkeeping even if agent_end is lost on cancellation.
      const now = Date.now();
      for (const [runId, expiresAt] of recoveringRuns) {
        if (expiresAt <= now) recoveringRuns.delete(runId);
      }
      if (ctx.trigger !== "heartbeat" || typeof event?.prompt !== "string" || !RECOVERY_PROMPTS.has(event.prompt.trim())) {
        return;
      }
      if (!ctx.runId) {
        api.logger.warn("heartbeat-recovery: dispatch guard unavailable without a host run ID; applying prompt guidance and tool filtering only");
      } else {
        recoveringRuns.set(ctx.runId, now + 60 * 60 * 1000);
      }
      api.logger.info("heartbeat-recovery: enforcing structured outcome for incomplete heartbeat");
      return { appendSystemContext: GUIDANCE, toolsAllow: ["heartbeat_respond"] };
    });
    // Forced delivery tools may survive prompt allowlists. Stop message dispatch
    // too, including a retained tool reference from the previous attempt.
    api.on("before_tool_call", (event, ctx) => {
      if (event.toolName === "message" && (recoveringRuns.get(ctx.runId) ?? 0) > Date.now()) {
        return { block: true, blockReason: "Heartbeat recovery must use heartbeat_respond; OpenClaw owns notification delivery." };
      }
    });
    api.on("agent_end", (_event, ctx) => {
      recoveringRuns.delete(ctx.runId);
    });
  },
};
