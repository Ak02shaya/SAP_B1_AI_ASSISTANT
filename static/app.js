/**
 * SAP Business One Copilot - Frontend Application Logic
 * Features: Continuous Non-Stop Voice-to-Text, Rotating "Thinking..." State, Zero Clutter
 */

document.addEventListener("DOMContentLoaded", () => {
  // --- 1. DOM Elements ---
  const loginScreen = document.getElementById("login-screen");
  const appScreen = document.getElementById("app-screen");
  const loginForm = document.getElementById("login-form");
  const loginError = document.getElementById("login-error");
  const usernameInput = document.getElementById("username");
  const passwordInput = document.getElementById("password");
  const togglePasswordBtn = document.getElementById("toggle-password");
  
  const sidebarUserName = document.getElementById("sidebar-user-name");
  const userAvatarInitial = document.getElementById("user-avatar-initial");
  const messagesContainer = document.getElementById("chat-messages-container");
  const messagesList = document.getElementById("messages-list");
  const emptyState = document.getElementById("empty-state");
  const chatForm = document.getElementById("chat-form");
  const promptInput = document.getElementById("prompt-input");
  const sendBtn = document.getElementById("send-btn");
  const micBtn = document.getElementById("mic-btn");
  const starterCards = document.querySelectorAll(".starter-card");
  const newChatBtn = document.getElementById("new-chat-btn");
  const clearSessionBtn = document.getElementById("clear-session-btn");
  const logoutBtn = document.getElementById("logout-btn");

  let currentUsername = sessionStorage.getItem("sap_user") || null;
  let activeCharts = [];
  let currentSessionId = "sess_" + Date.now();

  // --- Dynamic Per-User Conversation Management ---
  const convCountBadge = document.getElementById("conv-count-badge");
  const conversationsList = document.getElementById("conversations-list");

  function getStorageKey() {
    return "sap_conversations_" + (currentUsername || "guest");
  }

  function getUserConversations() {
    try {
      const data = localStorage.getItem(getStorageKey());
      return data ? JSON.parse(data) : [];
    } catch (e) {
      return [];
    }
  }

  function saveUserConversations(convs) {
    try {
      localStorage.setItem(getStorageKey(), JSON.stringify(convs));
    } catch (e) {
      console.warn("Storage quota exceeded or error saving chats", e);
    }
  }

  function formatTime(timestamp) {
    const d = new Date(timestamp);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  function renderConversationsList() {
    if (!conversationsList) return;
    const convs = getUserConversations();
    if (convCountBadge) {
      convCountBadge.textContent = convs.length;
    }
    conversationsList.innerHTML = "";

    if (convs.length === 0) {
      const emptyHint = document.createElement("div");
      emptyHint.className = "conv-empty-hint";
      emptyHint.innerHTML = "No saved chats yet.<br>Ask a question to begin.";
      conversationsList.appendChild(emptyHint);
      return;
    }

    convs.forEach(conv => {
      const item = document.createElement("div");
      item.className = `conversation-item ${conv.id === currentSessionId ? "active" : ""}`;
      item.setAttribute("data-id", conv.id);

      item.innerHTML = `
        <div class="conv-item-left">
          <span class="conv-item-icon">💬</span>
          <div class="conv-item-text">
            <span class="conv-item-title" title="${escapeHtml(conv.title)}">${escapeHtml(conv.title)}</span>
            <span class="conv-item-time">${escapeHtml(conv.timeStr || '')}</span>
          </div>
        </div>
        <button class="delete-conv-btn" title="Delete conversation" data-id="${conv.id}">🗑️</button>
      `;

      item.addEventListener("click", (e) => {
        if (e.target.closest(".delete-conv-btn")) return;
        selectConversation(conv.id);
      });

      const delBtn = item.querySelector(".delete-conv-btn");
      if (delBtn) {
        delBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          deleteConversation(conv.id);
        });
      }

      conversationsList.appendChild(item);
    });
  }

  function selectConversation(sessionId) {
    stopListening();
    currentSessionId = sessionId;
    const convs = getUserConversations();
    const conv = convs.find(c => c.id === sessionId);
    if (!conv) return;

    renderConversationsList();

    // Render all saved messages
    messagesList.innerHTML = "";
    emptyState.classList.add("hidden");

    if (conv.messages && conv.messages.length > 0) {
      conv.messages.forEach(msg => {
        try {
          if (msg.role === "user") {
            const row = document.createElement("div");
            row.className = "chat-row user";
            row.innerHTML = `
              <div class="chat-bubble">${escapeHtml(msg.text)}</div>
              <div class="chat-avatar">👤</div>
            `;
            messagesList.appendChild(row);
          } else if (msg.role === "assistant") {
            const row = document.createElement("div");
            row.className = "chat-row assistant";
            const bubble = document.createElement("div");
            bubble.className = "chat-bubble";

            const content = document.createElement("div");
            content.innerHTML = window.marked ? marked.parse(msg.text || "") : escapeHtml(msg.text || "");
            bubble.appendChild(content);

            if (msg.visual) {
              const chartBox = document.createElement("div");
              bubble.appendChild(chartBox);
              try {
                renderVisualChart(chartBox, msg.visual);
              } catch (chartErr) {
                console.warn("Could not render cached chart", chartErr);
              }
            }

            if (msg.sql) {
              const excelBox = document.createElement("div");
              const dlBtn = document.createElement("button");
              dlBtn.className = "excel-download-btn";
              dlBtn.innerHTML = `<span>📥 Download Full Excel Report (.xlsx)</span>`;
              dlBtn.onclick = () => downloadExcel(msg.sql);
              excelBox.appendChild(dlBtn);
              bubble.appendChild(excelBox);
            }

            if (msg.followups && msg.followups.length > 0) {
              const wrap = document.createElement("div");
              wrap.className = "followups-wrapper";
              msg.followups.forEach(f => {
                const b = document.createElement("button");
                b.className = "followup-btn";
                b.textContent = f;
                b.onclick = () => {
                  promptInput.value = f;
                  submitCurrentPrompt();
                };
                wrap.appendChild(b);
              });
              bubble.appendChild(wrap);
            }

            row.innerHTML = `<div class="chat-avatar">🤖</div>`;
            row.appendChild(bubble);
            messagesList.appendChild(row);
          }
        } catch (msgErr) {
          console.warn("Error rendering cached message", msgErr);
        }
      });
    } else {
      emptyState.classList.remove("hidden");
    }

    scrollToBottom();
  }

  function deleteConversation(sessionId) {
    let convs = getUserConversations();
    convs = convs.filter(c => c.id !== sessionId);
    saveUserConversations(convs);

    if (currentSessionId === sessionId) {
      createNewConversation();
    } else {
      renderConversationsList();
    }
  }

  function createNewConversation() {
    stopListening();
    currentSessionId = "sess_" + Date.now();
    messagesList.innerHTML = "";
    emptyState.classList.remove("hidden");
    renderConversationsList();
    promptInput.value = "";
    promptInput.focus();
  }

  function appendMessageToSession(role, data) {
    const convs = getUserConversations();
    let conv = convs.find(c => c.id === currentSessionId);
    if (!conv) {
      // First message creates new conversation title!
      const rawText = typeof data === "string" ? data : (data.text || "New Chat");
      const cleanTitle = rawText.length > 38 ? rawText.slice(0, 37).trim() + "..." : rawText.trim();
      const title = cleanTitle.charAt(0).toUpperCase() + cleanTitle.slice(1);

      conv = {
        id: currentSessionId,
        title: title,
        createdAt: Date.now(),
        timeStr: formatTime(Date.now()),
        messages: []
      };
      convs.unshift(conv);
    }

    if (role === "user") {
      conv.messages.push({ role: "user", text: typeof data === "string" ? data : data.text });
    } else {
      conv.messages.push({
        role: "assistant",
        text: data.text || "",
        visual: data.visual || null,
        sql: data.sql || null,
        followups: data.followups || []
      });
    }

    saveUserConversations(convs);
    renderConversationsList();
  }

  // --- 2. Password Visibility Toggle ---
  if (togglePasswordBtn && passwordInput) {
    togglePasswordBtn.addEventListener("click", () => {
      const isPassword = passwordInput.getAttribute("type") === "password";
      passwordInput.setAttribute("type", isPassword ? "text" : "password");
      togglePasswordBtn.textContent = isPassword ? "🙈" : "👁";
    });
  }

  // --- 3. Authentication Gate ---
  function showApp() {
    loginScreen.classList.add("hidden");
    appScreen.classList.remove("hidden");
    if (sidebarUserName && currentUsername) {
      sidebarUserName.textContent = currentUsername.charAt(0).toUpperCase() + currentUsername.slice(1);
    }
    if (userAvatarInitial && currentUsername) {
      userAvatarInitial.textContent = currentUsername.charAt(0).toUpperCase();
    }
    try {
      renderConversationsList();
    } catch (e) {
      console.warn("Error rendering conversations list", e);
    }
    createNewConversation();
  }

  function showLogin() {
    sessionStorage.removeItem("sap_user");
    currentUsername = null;
    appScreen.classList.add("hidden");
    loginScreen.classList.remove("hidden");
    passwordInput.value = "";
    loginError.classList.add("hidden");
    if (conversationsList) conversationsList.innerHTML = "";
    if (convCountBadge) convCountBadge.textContent = "0";
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.classList.add("hidden");

    const u = usernameInput.value.trim();
    const p = passwordInput.value;

    if (!u || !p) {
      loginError.textContent = "Please enter both username and password.";
      loginError.classList.remove("hidden");
      return;
    }

    const submitBtn = document.getElementById("login-btn");
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span>Signing in...</span>`;

    try {
      const res = await fetch("/api/v1/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: u, password: p })
      });

      if (res.ok) {
        const data = await res.json();
        currentUsername = data.username || u;
        sessionStorage.setItem("sap_user", currentUsername);
        showApp();
      } else if (res.status === 401) {
        loginError.textContent = "Invalid username or password. Please try again.";
        loginError.classList.remove("hidden");
      } else {
        const err = await res.json().catch(() => ({}));
        loginError.textContent = err.detail || "Authentication error occurred.";
        loginError.classList.remove("hidden");
      }
    } catch (err) {
      loginError.textContent = "Cannot reach server. Ensure FastAPI backend is running.";
      loginError.classList.remove("hidden");
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span>Sign In to Workspace</span><span class="btn-arrow">→</span>`;
    }
  });

  // --- 4. Logout & Clear Conversation ---
  logoutBtn.addEventListener("click", async () => {
    stopListening();
    try {
      await fetch("/api/v1/clear_conversation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "default" })
      });
    } catch (e) {}
    messagesList.innerHTML = "";
    emptyState.classList.remove("hidden");
    showLogin();
  });

  clearSessionBtn.addEventListener("click", async () => {
    try {
      await fetch("/api/v1/clear_conversation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "default" })
      });
    } catch (e) {}
    localStorage.removeItem(getStorageKey());
    createNewConversation();
  });

  newChatBtn.addEventListener("click", () => {
    createNewConversation();
  });

  // --- 5. Unified Prompt Submission ---
  function submitCurrentPrompt() {
    stopListening();
    const prompt = promptInput.value.trim();
    if (!prompt) return;
    promptInput.value = "";
    promptInput.style.height = "auto";
    handleUserMessage(prompt);
  }

  // --- 6. Quick-Start Prompt Cards ---
  starterCards.forEach(card => {
    card.addEventListener("click", () => {
      const promptText = card.getAttribute("data-prompt");
      if (promptText) {
        promptInput.value = promptText;
        submitCurrentPrompt();
      }
    });
  });

  // --- 7. Auto-Resizing Chat Textarea & Submission ---
  promptInput.addEventListener("input", () => {
    promptInput.style.height = "auto";
    promptInput.style.height = Math.min(promptInput.scrollHeight, 120) + "px";
  });

  promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitCurrentPrompt();
    }
  });

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    submitCurrentPrompt();
  });

  if (sendBtn) {
    sendBtn.addEventListener("click", (e) => {
      e.preventDefault();
      submitCurrentPrompt();
    });
  }

  // --- 7. Continuous Non-Stop Voice-to-Text with DSP Noise Cancellation ---
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let isListening = false;
  let committedTranscript = ""; // Remembers speech across breath pauses
  let audioStream = null;       // Active MediaStream with hardware noise suppression

  // Real-time SAP B1 / ERP Terminology Phonetic Auto-Correction
  const SAP_PHONETIC_REPLACEMENTS = [
    { re: /\b(cross|growth|gross)\s+(profit|profile|product|prove\s*it)\b/gi, sub: "gross profit" },
    { re: /\b(cross|growth)\s+margin\b/gi, sub: "gross margin" },
    { re: /\b(sub\s*hana|sapna|sep\s*hana|sap\s*hanna|sub\s*hannah)\b/gi, sub: "SAP HANA" },
    { re: /\b(where\s*house|wear\s*house|ware\s*houses|where\s*houses)\b/gi, sub: "warehouse" },
    { re: /\bgo\s*down\b/gi, sub: "godown" },
    { re: /\b(dock|dog|dark)\s+num(ber)?\b/gi, sub: "DocNum" },
    { re: /\b(dock|dog|dark)\s+entry\b/gi, sub: "DocEntry" },
    { re: /\bdoc\s+num\b/gi, sub: "DocNum" },
    { re: /\bdoc\s+entry\b/gi, sub: "DocEntry" },
    { re: /\b(g\s*s\s*t\s*i\s*n|just\s*in|testing|gst\s*in)\b/gi, sub: "GSTIN" },
    { re: /\bh\s*s\s*n(\s*code)?\b/gi, sub: "HSN" },
    { re: /\bp\s*a\s*n(\s*number|card)?\b/gi, sub: "PAN" },
    { re: /\b(good\s*rage|god\s*rage|god\s*rich)\b/gi, sub: "Godrej" },
    { re: /\b(we\s*won|veevo|v\s*e\s*e\s*v\s*o|we\s*bow)\b/gi, sub: "Vivo" },
    { re: /\b(some\s*sung|sam\s*sung)\b/gi, sub: "Samsung" },
    { re: /\b(havel|havels|howels)\b/gi, sub: "Havells" },
    { re: /\b(neck|net)\s+(sales?|sail)\b/gi, sub: "net sales" },
    { re: /\b(turn\s*over)\b/gi, sub: "turnover" },
    { re: /\b(out\s*standing)\b/gi, sub: "outstanding" },
    { re: /\b(in\s*voice|in\s*voices)\b/gi, sub: "invoice" },
    { re: /\b(p\s*and\s*l|p\s*&\s*l|profit\s*and\s*loss)\b/gi, sub: "P&L" },
    { re: /\b(year\s*to\s*date|y\s*o\s*y)\b/gi, sub: "YoY" },
    { re: /\b(month\s*to\s*date|m\s*o\s*m)\b/gi, sub: "MoM" },
    { re: /\b(top\s*selling)\b/gi, sub: "top selling" },
    { re: /\b(stock\s*value)\b/gi, sub: "stock value" },
    { re: /\b(stock\s*quantity|stock\s*count)\b/gi, sub: "stock quantity" }
  ];

  function correctSAPTerminology(text) {
    if (!text) return "";
    let cleaned = text;
    for (const rule of SAP_PHONETIC_REPLACEMENTS) {
      cleaned = cleaned.replace(rule.re, rule.sub);
    }
    return cleaned;
  }

  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = true;       // Stays on continuously!
    recognition.interimResults = true;   // Shows words live as you talk
    recognition.lang = "en-IN";          // Supports English (Indian & Global accents)

    recognition.onstart = () => {
      isListening = true;
      micBtn.classList.add("listening");
      micBtn.title = "Microphone is ON (Noise suppression active, click to stop or send)";
      promptInput.placeholder = "🎙️ Listening with noise suppression... speak at your pace";
      committedTranscript = promptInput.value.trim() ? promptInput.value.trim() + " " : "";
    };

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          committedTranscript += event.results[i][0].transcript + " ";
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      const rawCombined = (committedTranscript + interim).trimStart();
      promptInput.value = correctSAPTerminology(rawCombined);
      promptInput.style.height = "auto";
      promptInput.style.height = Math.min(promptInput.scrollHeight, 120) + "px";
    };

    // If browser auto-pauses on silence, AUTO-RESTART so mic NEVER dies until user stops or sends!
    recognition.onend = () => {
      if (isListening) {
        try {
          committedTranscript = promptInput.value.trim() ? promptInput.value.trim() + " " : "";
          recognition.start();
        } catch (e) {
          // If restart was too fast, wait 100ms and retry
          setTimeout(() => {
            if (isListening) {
              try { recognition.start(); } catch (err) { stopListening(); }
            }
          }, 100);
        }
      } else {
        stopListening();
      }
    };

    recognition.onerror = (event) => {
      // Ignore 'no-speech' error: user was simply thinking or taking a pause!
      if (event.error === "no-speech") {
        return;
      }
      console.warn("Speech recognition notice:", event.error);
      stopListening();
    };
  }

  async function startListening() {
    if (!recognition) {
      alert("Voice-to-Text is supported in Google Chrome, Microsoft Edge, and Safari. Please use a supported browser.");
      return;
    }

    // Activate OS/Browser hardware DSP noise suppression, acoustic echo cancellation, and AGC
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      try {
        if (!audioStream) {
          audioStream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true
            }
          });
        }
      } catch (err) {
        console.warn("Hardware noise cancellation notice:", err);
      }
    }

    try {
      recognition.start();
    } catch (e) {
      stopListening();
    }
  }

  function stopListening() {
    isListening = false;
    if (micBtn) {
      micBtn.classList.remove("listening");
      micBtn.title = "Voice to Text (Click to speak)";
    }
    if (promptInput) {
      promptInput.placeholder = "Ask about sales, stock, customers, or click mic to speak...";
    }
    if (recognition) {
      try { recognition.stop(); } catch (e) {}
    }
    if (audioStream) {
      try {
        audioStream.getTracks().forEach(t => t.stop());
      } catch (e) {}
      audioStream = null;
    }
  }

  if (micBtn) {
    micBtn.addEventListener("click", () => {
      if (isListening) {
        stopListening();
      } else {
        startListening();
      }
    });
  }

  // --- 8. Core Message Flow & Thinking Animation ---
  function wantsExcel(text) {
    return /\b(excel|xlsx|sheet|spreadsheet|export|download|report)\b/i.test(text);
  }

  function appendUserMessage(text) {
    emptyState.classList.add("hidden");

    const row = document.createElement("div");
    row.className = "chat-row user";
    row.innerHTML = `
      <div class="chat-bubble">${escapeHtml(text)}</div>
      <div class="chat-avatar">👤</div>
    `;
    messagesList.appendChild(row);
    scrollToBottom();
  }

  async function handleUserMessage(userPrompt) {
    appendUserMessage(userPrompt);
    appendMessageToSession("user", userPrompt);

    // Create assistant response container with ChatGPT-style Animated Thinking Card
    const msgId = "msg_" + Date.now();
    const row = document.createElement("div");
    row.className = "chat-row assistant";
    row.innerHTML = `
      <div class="chat-avatar">🤖</div>
      <div class="chat-bubble" id="${msgId}">
        <div class="thinking-card" id="thinking_${msgId}">
          <div class="thinking-header">
            <div class="thinking-spinner">
              <span class="thinking-sparkle">✦</span>
            </div>
            <span class="thinking-label">Thinking & querying SAP HANA...</span>
          </div>
          <div class="thinking-step" id="thinking_step_${msgId}">🧠 Analyzing business intent & rules...</div>
          <div class="thinking-shimmer-bar"></div>
        </div>
      </div>
    `;
    messagesList.appendChild(row);
    scrollToBottom();

    // Rotate intelligent thinking steps every 2.2 seconds
    const thinkingSteps = [
      "🧠 Analyzing business intent & rules...",
      "🔍 Checking SAP HANA table joins & UDFs...",
      "⚡ Querying real-time enterprise database...",
      "📊 Synthesizing insights & generating charts..."
    ];
    let stepIndex = 0;
    const stepEl = document.getElementById(`thinking_step_${msgId}`);
    const thinkingInterval = setInterval(() => {
      stepIndex = (stepIndex + 1) % thinkingSteps.length;
      if (stepEl) {
        stepEl.style.opacity = "0";
        setTimeout(() => {
          if (stepEl) {
            stepEl.textContent = thinkingSteps[stepIndex];
            stepEl.style.opacity = "1";
          }
        }, 150);
      }
    }, 2200);

    const bubbleEl = document.getElementById(msgId);
    let fullResponse = "";
    let capturedSql = null;
    let capturedVisual = null;
    let hasError = false;
    let hasStartedStreaming = false;

    // Containers inside the bubble (SQL and Metrics containers are completely omitted for a clean UI!)
    const contentContainer = document.createElement("div");
    const chartContainer = document.createElement("div");
    const excelContainer = document.createElement("div");
    const followupsContainer = document.createElement("div");

    try {
      const response = await fetch("/api/v1/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: userPrompt, session_id: "default" })
      });

      if (!response.ok) {
        throw new Error(`Server returned status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const chunk = JSON.parse(line);

            if (chunk.type === "metadata") {
              // Captured in memory for Excel download, but NOT displayed in UI
              capturedSql = chunk.sql;
            } else if (chunk.type === "chunk") {
              // First word arrives: clear thinking animation!
              if (!hasStartedStreaming) {
                hasStartedStreaming = true;
                clearInterval(thinkingInterval);
                bubbleEl.innerHTML = "";
                bubbleEl.appendChild(contentContainer);
                bubbleEl.appendChild(chartContainer);
                bubbleEl.appendChild(excelContainer);
                bubbleEl.appendChild(followupsContainer);
              }

              fullResponse += chunk.text;
              contentContainer.innerHTML = window.marked ? marked.parse(fullResponse) : escapeHtml(fullResponse);
              scrollToBottom();
            } else if (chunk.type === "visual") {
              capturedVisual = chunk.visual;
              renderVisualChart(chartContainer, capturedVisual);
            } else if (chunk.type === "clarification_menu") {
              if (!hasStartedStreaming) {
                hasStartedStreaming = true;
                clearInterval(thinkingInterval);
                bubbleEl.innerHTML = "";
                bubbleEl.appendChild(contentContainer);
                bubbleEl.appendChild(chartContainer);
                bubbleEl.appendChild(excelContainer);
                bubbleEl.appendChild(followupsContainer);
              }
              contentContainer.innerHTML = `<div style="color: var(--accent); font-weight: 600; margin-bottom: 8px;">${escapeHtml(chunk.message || 'Please clarify:')}</div>`;
              if (chunk.options && chunk.options.length) {
                const optRow = document.createElement("div");
                optRow.className = "followups-wrapper";
                chunk.options.forEach(opt => {
                  const btn = document.createElement("button");
                  btn.className = "followup-btn";
                  btn.textContent = opt;
                  btn.onclick = () => handleUserMessage(`${userPrompt} (Use exactly: ${opt})`);
                  optRow.appendChild(btn);
                });
                followupsContainer.appendChild(optRow);
              }
            } else if (chunk.type === "metrics") {
              // Silently log to console for debugging, completely hidden from users!
              console.log("Telemetry metrics:", chunk);
            } else if (chunk.type === "error") {
              hasError = true;
              clearInterval(thinkingInterval);
              bubbleEl.innerHTML = `<div class="login-error-alert">${escapeHtml(chunk.text)}</div>`;
            }
          } catch (e) {
            console.error("Error parsing NDJSON chunk", e);
          }
        }
      }

      clearInterval(thinkingInterval);

      // Post-process response: Parse follow-up buttons ([BUTTON])
      if (!hasError && fullResponse) {
        const rawLines = fullResponse.split("\n");
        const cleanLines = [];
        const followups = [];

        for (const line of rawLines) {
          if (line.includes("[BUTTON]")) {
            followups.push(line.replace("[BUTTON]", "").trim());
          } else {
            cleanLines.push(line);
          }
        }

        fullResponse = cleanLines.join("\n").trim();
        contentContainer.innerHTML = window.marked ? marked.parse(fullResponse) : escapeHtml(fullResponse);

        if (followups.length > 0) {
          const wrap = document.createElement("div");
          wrap.className = "followups-wrapper";
          followups.forEach(f => {
            const b = document.createElement("button");
            b.className = "followup-btn";
            b.textContent = f;
            b.onclick = () => handleUserMessage(f);
            wrap.appendChild(b);
          });
          followupsContainer.appendChild(wrap);
        }

        // Add Excel download button if SQL exists or user asked for Excel
        if (capturedSql && wantsExcel(userPrompt)) {
          const dlBtn = document.createElement("button");
          dlBtn.className = "excel-download-btn";
          dlBtn.innerHTML = `<span>📥 Download Full Excel Report (.xlsx)</span>`;
          dlBtn.onclick = () => downloadExcel(capturedSql);
          excelContainer.appendChild(dlBtn);
        }

        // Persist completed assistant response in active conversation
        appendMessageToSession("assistant", {
          text: fullResponse,
          visual: capturedVisual,
          sql: capturedSql,
          followups: followups
        });
      }

    } catch (err) {
      clearInterval(thinkingInterval);
      bubbleEl.innerHTML = `<div class="login-error-alert">Connection Error: ${escapeHtml(err.message)}</div>`;
    }

    scrollToBottom();
  }

  // --- 9. Plotly Visual Rendering (Permanent Dark Palette) ---
  function renderVisualChart(container, visual) {
    if (!visual || !visual.plotly_fig || !window.Plotly) return;

    const chartDivId = "chart_" + Math.random().toString(36).substring(2, 9);
    const chartWrapper = document.createElement("div");
    chartWrapper.className = "chart-container";
    chartWrapper.innerHTML = `<div id="${chartDivId}" style="width: 100%; min-height: 380px;"></div>`;
    container.appendChild(chartWrapper);

    const fig = visual.plotly_fig;

    if (fig.layout) {
      fig.layout.font = { color: "#F4F4F6", family: "Inter, sans-serif" };
      fig.layout.paper_bgcolor = "rgba(0,0,0,0)";
      fig.layout.plot_bgcolor = "rgba(0,0,0,0)";
      if (!fig.layout.hoverlabel) {
        fig.layout.hoverlabel = {
          bgcolor: "#1E222A",
          font: { color: "#F4F4F6", family: "Inter, sans-serif", size: 13 },
          bordercolor: "rgba(255, 255, 255, 0.15)"
        };
      }
      if (fig.layout.xaxis) {
        fig.layout.xaxis.gridcolor = "rgba(255,255,255,0.08)";
        fig.layout.xaxis.color = "#A1A7B5";
      }
      if (fig.layout.yaxis) {
        fig.layout.yaxis.gridcolor = "rgba(255,255,255,0.08)";
        fig.layout.yaxis.color = "#A1A7B5";
      }
    }

    Plotly.newPlot(chartDivId, fig.data, fig.layout, { responsive: true, displayModeBar: false });
    activeCharts.push(chartDivId);
    scrollToBottom();
  }

  // --- 10. Excel Downloader ---
  async function downloadExcel(sql) {
    try {
      const res = await fetch("/api/v1/export_excel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql })
      });

      if (!res.ok) throw new Error("Excel export failed");

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `SAP_Report_${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      alert("Failed to export Excel report: " + e.message);
    }
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // --- 11. Initial App Boot (Runs after all listeners are registered!) ---
  if (currentUsername) {
    showApp();
  } else {
    showLogin();
  }
});
