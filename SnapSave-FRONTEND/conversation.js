// Shared, text-only presentation for operational updates and composer feedback.
window.conversationFeedback = function (id, text = "", error = false) {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = text;
  node.dataset.error = String(error);
};
window.mergeConversation = function (cached, incoming) {
  return [...new Map([...cached, ...incoming].map(m => [m.id, m])).values()]
    .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)) || a.id.localeCompare(b.id)).slice(-500);
};
window.conversationEvent = function (message, time) {
  if (message.sender_role !== "SYSTEM" || ["quote", "payment"].includes(message.kind)) return null;
  const node = document.createElement("div");
  node.className = "conversation-event";
  // Old records contain presentation markup. Show readable text without parsing HTML.
  node.textContent = String(message.message || "").replace(/<br\s*\/?\s*>/gi, "\n").replace(/<[^>]*>/g, "").trim();
  if (time) { const stamp = document.createElement("time"); stamp.textContent = time; node.append(stamp); }
  return node;
};
