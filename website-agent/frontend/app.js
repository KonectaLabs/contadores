const state = { users: [], user: null, messages: [], polling: null };

const usersElement = document.querySelector("#users");
const emptyState = document.querySelector("#empty-state");
const conversation = document.querySelector("#conversation");
const messagesElement = document.querySelector("#messages");
const chatName = document.querySelector("#chat-name");
const chatStatus = document.querySelector("#chat-status");
const avatar = document.querySelector("#avatar");
const composer = document.querySelector("#composer");
const messageInput = document.querySelector("#message");
const filesInput = document.querySelector("#files");
const selectedFiles = document.querySelector("#selected-files");
const userDialog = document.querySelector("#user-dialog");
const userForm = document.querySelector("#user-form");

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

function initials(name) {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function renderUsers() {
  usersElement.replaceChildren(...state.users.map((user) => {
    const button = document.createElement("button");
    button.className = `user${state.user?.id === user.id ? " active" : ""}`;
    button.innerHTML = `<span class="avatar"></span><span class="user-copy"><strong></strong><span></span></span>`;
    button.querySelector(".avatar").textContent = initials(user.name);
    button.querySelector("strong").textContent = user.name;
    button.querySelector(".user-copy span").textContent = user.phone;
    button.addEventListener("click", () => selectUser(user));
    return button;
  }));
}

function attachmentUrl(attachment) {
  return `/api/users/${state.user.id}/files${attachment.path}`;
}

function renderAttachment(attachment) {
  const type = attachment.content_type;
  let element;
  if (type.startsWith("image/")) {
    element = document.createElement("img");
    element.alt = attachment.name;
  } else if (type.startsWith("video/")) {
    element = document.createElement("video");
    element.controls = true;
  } else if (type.startsWith("audio/")) {
    element = document.createElement("audio");
    element.controls = true;
  } else {
    element = document.createElement("a");
    element.textContent = `Abrir ${attachment.name}`;
    element.target = "_blank";
  }
  element.className = "attachment";
  if (element.tagName === "A") element.href = attachmentUrl(attachment);
  else element.src = attachmentUrl(attachment);
  return element;
}

function appendLinkedText(container, text) {
  const links = /(https?:\/\/[^\s]+|\/preview\/[^\s]+)/g;
  let cursor = 0;
  for (const match of text.matchAll(links)) {
    container.append(document.createTextNode(text.slice(cursor, match.index)));
    const link = document.createElement("a");
    link.href = match[0];
    link.target = "_blank";
    link.textContent = match[0];
    container.append(link);
    cursor = match.index + match[0].length;
  }
  container.append(document.createTextNode(text.slice(cursor)));
}

function renderMessages() {
  const wasNearBottom = messagesElement.scrollHeight - messagesElement.scrollTop - messagesElement.clientHeight < 120;
  messagesElement.replaceChildren(...state.messages.map((message) => {
    const bubble = document.createElement("article");
    bubble.className = `message ${message.role === "user" ? "user-message" : "assistant-message"}`;
    for (const attachment of message.attachments) bubble.append(renderAttachment(attachment));
    if (message.text) {
      const text = document.createElement("div");
      text.className = "message-text";
      appendLinkedText(text, message.text);
      bubble.append(text);
    }
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const time = new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    meta.textContent = `${time}${message.role === "user" ? ` · ${message.status === "read" ? "✓✓" : message.status === "failed" ? "error" : "✓"}` : ""}`;
    bubble.append(meta);
    return bubble;
  }));
  if (wasNearBottom) messagesElement.scrollTop = messagesElement.scrollHeight;

  const working = state.messages.some((message) => message.role === "user" && ["queued", "processing"].includes(message.status));
  chatStatus.textContent = working ? "Website Agent está trabajando…" : "en línea";
  chatStatus.classList.toggle("working", working);
}

async function loadMessages() {
  if (!state.user) return;
  const messages = await api(`/api/users/${state.user.id}/messages`);
  if (JSON.stringify(messages) === JSON.stringify(state.messages)) return;
  state.messages = messages;
  renderMessages();
}

async function selectUser(user) {
  state.user = user;
  renderUsers();
  emptyState.classList.add("hidden");
  conversation.classList.remove("hidden");
  chatName.textContent = user.name;
  avatar.textContent = initials(user.name);
  state.messages = [];
  renderMessages();
  await loadMessages();
  clearInterval(state.polling);
  state.polling = setInterval(loadMessages, 1000);
  messageInput.focus();
}

async function loadUsers() {
  state.users = await api("/api/users");
  renderUsers();
  if (!state.user && state.users.length) await selectUser(state.users[0]);
}

function openUserDialog() {
  userDialog.showModal();
  userForm.elements.name.focus();
}

document.querySelector("#new-user").addEventListener("click", openUserDialog);
document.querySelector("#empty-new-user").addEventListener("click", openUserDialog);
document.querySelector("#close-dialog").addEventListener("click", () => userDialog.close());

userForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(userForm);
  const user = await api("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: form.get("name"), phone: form.get("phone") }),
  });
  userForm.reset();
  userDialog.close();
  await loadUsers();
  await selectUser(user);
});

filesInput.addEventListener("change", () => {
  selectedFiles.replaceChildren(...[...filesInput.files].map((file) => {
    const chip = document.createElement("span");
    chip.className = "file-chip";
    chip.textContent = file.name;
    return chip;
  }));
});

messageInput.addEventListener("input", () => {
  messageInput.style.height = "auto";
  messageInput.style.height = `${messageInput.scrollHeight}px`;
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.user) return;
  const text = messageInput.value;
  const files = [...filesInput.files];
  if (!text.trim() && !files.length) return;

  messageInput.value = "";
  messageInput.style.height = "auto";
  filesInput.value = "";
  selectedFiles.replaceChildren();

  const form = new FormData();
  form.append("text", text);
  for (const file of files) form.append("files", file);
  await api(`/api/users/${state.user.id}/messages`, { method: "POST", body: form });
  await loadMessages();
  messageInput.focus();
});

loadUsers();
