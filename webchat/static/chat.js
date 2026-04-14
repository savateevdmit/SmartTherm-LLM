(() => {
  "use strict";

  const TURNSTILE_SITE_KEY = window.__TURNSTILE_SITE_KEY || "";
  const POLL_INTERVAL_MS   = 2000;
  const MAX_POLL_ATTEMPTS  = 180;
  const LONG_WAIT_MS       = 120000;

  const chat            = document.getElementById("chat");
  const userInput       = document.getElementById("userInput");
  const sendBtn         = document.getElementById("sendBtn");
  const usernameToggle  = document.getElementById("usernameToggle");
  const usernameInputW  = document.getElementById("usernameInputWrap");
  const tgUsernameInput = document.getElementById("tgUsername");
  const usernameSave    = document.getElementById("usernameSave");
  const usernameText    = document.getElementById("usernameToggleText");
  const turnstileWrap   = document.getElementById("turnstileWrap");

  let isBusy         = false;
  let tgUsername      = localStorage.getItem("st_tg_user") || "";
  let welcomeRemoved = false;
  let turnstileToken = "";
  let turnstileWidgetId = null;

  if (tgUsername) {
    tgUsernameInput.value = tgUsername;
    usernameText.textContent = `Telegram: @${tgUsername}`;
  }

  function initTurnstile() {
    if (!TURNSTILE_SITE_KEY || turnstileWidgetId !== null) return;
    if (typeof turnstile === "undefined") {
      setTimeout(initTurnstile, 500);
      return;
    }
    turnstileWrap.style.display = "block";
    turnstileWidgetId = turnstile.render(turnstileWrap, {
      sitekey: TURNSTILE_SITE_KEY,
      callback: (token) => { turnstileToken = token; },
      "error-callback": () => { turnstileToken = ""; },
      "expired-callback": () => { turnstileToken = ""; },
      size: "invisible",
    });
  }
  initTurnstile();

  usernameToggle.addEventListener("click", () => {
    const open = usernameInputW.classList.toggle("open");
    usernameToggle.setAttribute("aria-expanded", open);
    if (open) tgUsernameInput.focus();
  });

  usernameSave.addEventListener("click", () => {
    const val = (tgUsernameInput.value || "").trim().replace(/^@/, "");
    tgUsername = val;
    localStorage.setItem("st_tg_user", val);
    usernameInputW.classList.remove("open");
    usernameText.textContent = val ? `Telegram: @${val}` : "Указать Telegram для обратной связи";
  });

  tgUsernameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); usernameSave.click(); }
  });

  userInput.addEventListener("input", () => {
    userInput.style.height = "auto";
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + "px";
    sendBtn.disabled = !userInput.value.trim() || isBusy;
  });

  userInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!sendBtn.disabled) send();
    }
  });

  sendBtn.addEventListener("click", send);

  function removeWelcome() {
    if (welcomeRemoved) return;
    const w = chat.querySelector(".chat__welcome");
    if (w) w.remove();
    welcomeRemoved = true;
  }

  function addBubble(cls, html) {
    removeWelcome();
    const div = document.createElement("div");
    div.className = `bubble ${cls}`;
    div.innerHTML = html;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
  }

  function addTyping() {
    removeWelcome();
    const div = document.createElement("div");
    div.className = "typing";
    div.id = "typingIndicator";
    div.innerHTML = "<span></span><span></span><span></span>";
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
  }

  function removeTyping() {
    const el = document.getElementById("typingIndicator");
    if (el) el.remove();
  }

  function removeStatusBubble() {
    const el = document.getElementById("statusBubble");
    if (el) el.remove();
  }

  function escapeHtml(text) {
    const d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
  }

  function formatEta(seconds) {
    if (seconds <= 60) return `${seconds} сек`;
    const minutes = Math.ceil(seconds / 60);
    return `${minutes} мин`;
  }

  function linkify(html) {
    const parts = html.split(/(<a\s[^>]*>[\s\S]*?<\/a>|<[^>]+>)/gi);
    return parts.map((part, i) => {
      if (i % 2 === 1) return part;
      return part.replace(
        /(https?:\/\/[^\s<>"')\]]+)/gi,
        '<a href="$1" target="_blank" rel="noopener">$1</a>'
      );
    }).join("");
  }

  function formatBotHtml(raw) {
    let s = raw || "";
    const parts = s.split(/(<pre[\s\S]*?<\/pre>)/gi);
    const formatted = parts.map((p, i) => {
      if (i % 2 === 1) return p;
      let text = p.replace(/\n/g, "<br>");
      text = linkify(text);
      return text;
    }).join("");
    return formatted;
  }

  async function send() {
    const text = (userInput.value || "").trim();
    if (!text || isBusy) return;

    isBusy = true;
    sendBtn.disabled = true;
    userInput.value = "";
    userInput.style.height = "auto";

    addBubble("bubble--user", escapeHtml(text));

    if (TURNSTILE_SITE_KEY && turnstileWidgetId !== null && !turnstileToken) {
      try { turnstile.reset(turnstileWidgetId); } catch (_) {}
      await new Promise(r => setTimeout(r, 1000));
    }

    try {
      const resp = await fetch("chat/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          tg_username: tgUsername,
          cf_token: turnstileToken || "",
        }),
      });

      if (TURNSTILE_SITE_KEY && turnstileWidgetId !== null) {
        turnstileToken = "";
        try { turnstile.reset(turnstileWidgetId); } catch (_) {}
      }

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const msg = {
          captcha_required: "Пожалуйста, дождитесь проверки капчи и попробуйте снова.",
          captcha_failed: "Проверка капчи не пройдена. Обновите страницу и попробуйте ещё раз.",
          rate_limited: "Слишком много запросов. Подождите минуту и попробуйте снова.",
          invalid_text: "Текст вопроса пустой или слишком длинный (макс. 2000 символов).",
        }[err.error] || "Произошла ошибка. Попробуйте позже.";
        addBubble("bubble--error", escapeHtml(msg));
        isBusy = false;
        return;
      }

      const data = await resp.json();
      const taskId = data.task_id;
      if (!taskId) throw new Error("No task_id in response");

      const position = data.queue_position || 1;
      const etaSec = data.eta_seconds || position * 30;
      const statusDiv = addBubble("bubble--status",
        `Ваш вопрос принят, уже готовим для вас ответ.<br>` +
        `<b>Позиция в очереди:</b> ${position}<br>` +
        `<b>Примерное время ожидания:</b> ${formatEta(etaSec)}`
      );
      statusDiv.id = "statusBubble";

      addTyping();

      await pollResult(taskId);
    } catch (e) {
      removeTyping();
      removeStatusBubble();
      addBubble("bubble--error", "Ошибка связи с сервером. Попробуйте позже.");
      console.error(e);
    }

    isBusy = false;
    sendBtn.disabled = !userInput.value.trim();
  }

  async function pollResult(taskId) {
    let longWaitShown = false;
    const startTime = Date.now();

    for (let i = 0; i < MAX_POLL_ATTEMPTS; i++) {
      await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));

      if (!longWaitShown && Date.now() - startTime >= LONG_WAIT_MS) {
        longWaitShown = true;
        removeStatusBubble();
        addBubble("bubble--status",
          "Готовим ответ, это занимает чуть больше времени. Пожалуйста, подождите\u2026"
        );
      }

      try {
        const resp = await fetch("chat/poll", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_id: taskId }),
        });

        if (!resp.ok) continue;
        const data = await resp.json();

        if (data.status === "pending") continue;

        removeTyping();
        removeStatusBubble();

        if (data.error) {
          addBubble("bubble--error", "Ошибка генерации ответа. Попробуйте позже.");
          return;
        }

        const answerHtml = formatBotHtml(data.answer_text || "Нет ответа.");
        const bubble = addBubble("bubble--bot", answerHtml);

        if (data.media_ids && data.media_ids.length > 0) {
          const grid = document.createElement("div");
          grid.className = "media-grid";
          data.media_ids.forEach((mid) => {
            const img = document.createElement("img");
            img.src = `chat/media/${mid}`;
            img.alt = `Изображение ${mid}`;
            img.loading = "lazy";
            img.addEventListener("click", () => openLightbox(img.src));
            grid.appendChild(img);
          });
          bubble.appendChild(grid);
        }

        return;
      } catch (_) {
      }
    }

    removeTyping();
    removeStatusBubble();
    addBubble("bubble--error", "Таймаут. Сервер не ответил вовремя. Попробуйте позже.");
  }

  function openLightbox(src) {
    const lb = document.createElement("div");
    lb.className = "lightbox";
    lb.innerHTML = `<img src="${src}" />`;
    lb.addEventListener("click", () => lb.remove());
    document.body.appendChild(lb);
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const lb = document.querySelector(".lightbox");
      if (lb) lb.remove();
    }
  });
})();