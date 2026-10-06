(function () {
  "use strict";

  var POLL_MS = 1000;
  var MAX_POLL_FAILURES = 5;
  var BASE_TITLE = "Multi-Agent Orchestration System";
  var EXAMPLES = [
    "Research upcoming technology events and summarize the useful findings with sources.",
    "Compare the main open-source tools for running large language models locally.",
    "Summarize recent news about renewable energy storage, with sources."
  ];
  var STEPS = [
    { key: "plan", name: "Plan", note: "Supervisor" },
    { key: "research", name: "Research", note: "Research Agent" },
    { key: "review", name: "Review", note: "Reviewer" },
    { key: "final", name: "Answer", note: "Final report" }
  ];
  var STAGE_STEP = { plan: 0, research: 1, revise: 1, review: 2, finalize: 3 };

  function $(id) {
    return document.getElementById(id);
  }

  var els = {
    form: $("goal-form"),
    goal: $("goal"),
    counter: $("counter"),
    runButton: $("run-button"),
    examples: $("examples"),
    banner: $("banner"),
    empty: $("empty-state"),
    runPanel: $("run-panel"),
    runId: $("run-id"),
    runTitle: $("run-title"),
    runBadge: $("run-badge"),
    runElapsed: $("run-elapsed"),
    stepper: $("stepper"),
    caption: $("stage-caption"),
    tasksBlock: $("tasks-block"),
    tasksCount: $("tasks-count"),
    tasks: $("tasks"),
    reviewBlock: $("review-block"),
    reviewVerdict: $("review-verdict"),
    reviewRevisions: $("review-revisions"),
    reviewIssues: $("review-issues"),
    errorsBlock: $("errors-block"),
    errors: $("errors"),
    retry: $("retry-button"),
    resultPanel: $("result-panel"),
    resultBody: $("result-body"),
    copy: $("copy-button"),
    download: $("download-button"),
    history: $("history"),
    historyEmpty: $("history-empty"),
    pill: $("setup-pill"),
    version: $("version"),
    theme: $("theme-toggle")
  };

  var state = {
    maxGoalChars: 2000,
    currentId: null,
    pollTimer: null,
    pollFailures: 0,
    renderedResultFor: null,
    lastOutput: "",
    submitting: false,
    setupBannerShown: false
  };

  // ---------- DOM helpers (text nodes only, so data can never become markup) ----------

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function formatElapsed(seconds) {
    var total = Math.max(0, Math.round(seconds));
    var minutes = Math.floor(total / 60);
    var rest = total % 60;
    return minutes > 0 ? minutes + "m " + (rest < 10 ? "0" : "") + rest + "s" : total + "s";
  }

  function formatTime(iso) {
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  // ---------- API ----------

  function ApiError(status, message) {
    this.status = status;
    this.message = message;
  }

  function messageFrom(data, fallback) {
    if (!data || data.detail === undefined) return fallback;
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail) && data.detail.length > 0) {
      var first = data.detail[0];
      var text = first && typeof first.msg === "string" ? first.msg : fallback;
      return text.replace(/^Value error,\s*/, "");
    }
    return fallback;
  }

  function api(path, options) {
    return fetch(path, options).then(function (response) {
      return response
        .json()
        .catch(function () {
          return null;
        })
        .then(function (data) {
          if (!response.ok) {
            throw new ApiError(response.status, messageFrom(data, "Request failed (" + response.status + ")."));
          }
          return data;
        });
    });
  }

  // ---------- Safe markdown ----------

  var INLINE = new RegExp(
    [
      "`([^`\\n]+)`",
      "\\*\\*([^*\\n]+)\\*\\*",
      "\\*([^*\\s][^*\\n]*?)\\*",
      "\\[([^\\]\\n]+)\\]\\((https?:\\/\\/[^\\s)]+)\\)",
      "\\[(\\d{1,3})\\]",
      "(https?:\\/\\/[^\\s<>()\"'\\]]+)"
    ].join("|"),
    "g"
  );

  function makeLink(url, label) {
    var link = el("a", "", label);
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer nofollow";
    return link;
  }

  function inline(text, parent) {
    var last = 0;
    var match;
    INLINE.lastIndex = 0;
    while ((match = INLINE.exec(text)) !== null) {
      if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
      if (match[1] !== undefined) {
        parent.appendChild(el("code", "", match[1]));
      } else if (match[2] !== undefined) {
        var strong = el("strong");
        inline(match[2], strong);
        parent.appendChild(strong);
      } else if (match[3] !== undefined) {
        var em = el("em");
        inline(match[3], em);
        parent.appendChild(em);
      } else if (match[4] !== undefined) {
        parent.appendChild(makeLink(match[5], match[4]));
      } else if (match[6] !== undefined) {
        parent.appendChild(el("span", "cite", match[6]));
      } else if (match[7] !== undefined) {
        var url = match[7].replace(/[.,;:!?]+$/, "");
        parent.appendChild(makeLink(url, url));
        if (url.length < match[7].length) {
          parent.appendChild(document.createTextNode(match[7].slice(url.length)));
        }
      }
      last = INLINE.lastIndex;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  var BULLET = /^\s*[-*]\s+(.*)$/;
  var NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
  var HEADING = /^(#{1,4})\s+(.*)$/;

  function startsBlock(line) {
    return /^```/.test(line) || HEADING.test(line) || BULLET.test(line) || NUMBERED.test(line);
  }

  function renderMarkdown(source, root) {
    clear(root);
    var lines = source.replace(/\r\n?/g, "\n").split("\n");
    var i = 0;
    var sourcesNext = false;

    while (i < lines.length) {
      var line = lines[i];
      if (!line.trim()) {
        i += 1;
        continue;
      }

      if (/^```/.test(line)) {
        var code = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) {
          code.push(lines[i]);
          i += 1;
        }
        i += 1;
        var pre = el("pre");
        pre.appendChild(el("code", "", code.join("\n")));
        root.appendChild(pre);
        continue;
      }

      var heading = HEADING.exec(line);
      if (heading) {
        var level = Math.min(heading[1].length, 4);
        var h = el("h" + level);
        inline(heading[2], h);
        root.appendChild(h);
        i += 1;
        continue;
      }

      var isBullet = BULLET.test(line);
      if (isBullet || NUMBERED.test(line)) {
        var list = el(isBullet ? "ul" : "ol");
        if (isBullet && sourcesNext) list.className = "sources";
        sourcesNext = false;
        var pattern = isBullet ? BULLET : NUMBERED;
        var item = null;
        while (i < lines.length && lines[i].trim()) {
          var itemMatch = pattern.exec(lines[i]);
          if (itemMatch) {
            item = el("li");
            inline(itemMatch[1], item);
            list.appendChild(item);
          } else if (item && !startsBlock(lines[i])) {
            item.appendChild(document.createTextNode(" "));
            inline(lines[i].trim(), item);
          } else {
            break;
          }
          i += 1;
        }
        root.appendChild(list);
        continue;
      }

      var paragraph = [];
      while (i < lines.length && lines[i].trim() && (paragraph.length === 0 || !startsBlock(lines[i]))) {
        paragraph.push(lines[i].trim());
        i += 1;
      }
      var text = paragraph.join(" ");
      if (text === "**Sources**") {
        root.appendChild(el("p", "sources-label", "Sources"));
        sourcesNext = true;
        continue;
      }
      sourcesNext = false;
      var p = el("p", /^\*\*Task:\*\*/.test(text) ? "task-line" : "");
      inline(text, p);
      root.appendChild(p);
    }
  }

  // ---------- Rendering ----------

  function setBadge(node, value) {
    node.className = "badge badge-" + value;
    node.textContent = value;
  }

  function showBanner(message, title, bad) {
    clear(els.banner);
    if (title) els.banner.appendChild(el("strong", "", title));
    els.banner.appendChild(document.createTextNode(message));
    els.banner.className = bad ? "banner bad" : "banner";
    els.banner.hidden = false;
  }

  function hideBanner() {
    els.banner.hidden = true;
  }

  function failedStepIndex(view) {
    if (view.tasks.length === 0) return 0;
    if (view.review) return 2;
    var broken = view.tasks.some(function (task) {
      return task.status === "failed" || task.status === "blocked";
    });
    return broken ? 1 : 2;
  }

  function renderStepper(view) {
    var failed = view.status === "failed";
    var done = view.status === "done";
    var active = failed ? failedStepIndex(view) : STAGE_STEP[view.stage];
    clear(els.stepper);
    STEPS.forEach(function (step, index) {
      var stepState = "pending";
      if (done || index < active) stepState = "done";
      else if (index === active) stepState = failed ? "failed" : "active";
      var item = el("li", "step");
      item.dataset.state = stepState;
      item.appendChild(el("div", "step-name", step.name));
      var note = stepState === "failed" ? "Stopped here" : step.note;
      item.appendChild(el("div", "step-note", note));
      if (stepState === "active") item.setAttribute("aria-current", "step");
      els.stepper.appendChild(item);
    });
  }

  function captionFor(view) {
    var done = view.tasks.filter(function (task) {
      return task.status === "done";
    }).length;
    switch (view.stage) {
      case "plan":
        return "The Supervisor is planning the tasks.";
      case "research":
        return "The Research Agent is searching and summarizing. " + done + " of " + view.tasks.length + " tasks done.";
      case "review":
        return "The Reviewer is checking the results against your goal.";
      case "revise":
        return "The Reviewer asked for changes. The affected tasks run again.";
      case "finalize":
        return "Building the final answer.";
      case "done":
        return "Finished in " + formatElapsed(view.elapsed_seconds) + ".";
      default:
        return "The run stopped before it produced an answer.";
    }
  }

  function renderTasks(view) {
    els.tasksBlock.hidden = view.tasks.length === 0;
    els.tasksCount.textContent = view.tasks.length ? "(" + view.tasks.length + ")" : "";
    clear(els.tasks);
    view.tasks.forEach(function (task) {
      var row = el("li", "task");
      row.appendChild(el("span", "task-id mono", task.id));
      var body = el("div");
      body.appendChild(el("div", "task-desc", task.description));
      if (task.attempts > 1 || task.status === "failed") {
        body.appendChild(el("div", "task-meta", "Attempts: " + task.attempts));
      }
      if (task.error) body.appendChild(el("div", "task-error", task.error));
      row.appendChild(body);
      var badge = el("span");
      setBadge(badge, task.status);
      row.appendChild(badge);
      els.tasks.appendChild(row);
    });
  }

  function renderReview(view) {
    var review = view.review;
    els.reviewBlock.hidden = !review;
    if (!review) return;
    setBadge(els.reviewVerdict, review.verdict);
    els.reviewRevisions.textContent =
      review.revision_count > 0 ? "Revisions used: " + review.revision_count : "";
    clear(els.reviewIssues);
    review.issues.forEach(function (issue) {
      els.reviewIssues.appendChild(el("li", "", issue));
    });
  }

  function renderErrors(view) {
    var failed = view.status === "failed";
    var hasErrors = view.errors.length > 0;
    els.errorsBlock.hidden = !(hasErrors || failed);
    if (els.errorsBlock.hidden) return;
    els.errorsBlock.querySelector(".section-title").textContent = failed
      ? "What went wrong"
      : "Problems so far";
    clear(els.errors);
    var messages = hasErrors ? view.errors : ["The run did not finish. No details were recorded."];
    messages.forEach(function (message) {
      els.errors.appendChild(el("li", "", message));
    });
    els.retry.hidden = !failed;
  }

  function renderResult(view) {
    var ready = view.status === "done" && !!view.final_output;
    els.resultPanel.hidden = !ready;
    if (!ready) {
      state.renderedResultFor = null;
      state.lastOutput = "";
      return;
    }
    if (state.renderedResultFor !== view.id) {
      renderMarkdown(view.final_output, els.resultBody);
      state.renderedResultFor = view.id;
      state.lastOutput = view.final_output;
    }
  }

  function renderRun(view) {
    els.empty.hidden = true;
    els.runPanel.hidden = false;
    els.runId.textContent = view.id;
    els.runTitle.textContent = view.goal;
    setBadge(els.runBadge, view.status);
    els.runElapsed.textContent = formatElapsed(view.elapsed_seconds);
    renderStepper(view);
    els.caption.textContent = captionFor(view);
    renderTasks(view);
    renderReview(view);
    renderErrors(view);
    renderResult(view);

    if (view.status === "running") document.title = "Running · " + BASE_TITLE;
    else if (view.status === "done") document.title = "Done · " + BASE_TITLE;
    else document.title = "Failed · " + BASE_TITLE;
  }

  function clearRunView() {
    els.runPanel.hidden = true;
    els.resultPanel.hidden = true;
    els.empty.hidden = false;
    state.renderedResultFor = null;
    document.title = BASE_TITLE;
  }

  function renderHistory(items) {
    clear(els.history);
    els.historyEmpty.hidden = items.length > 0;
    items.forEach(function (item) {
      var row = el("li");
      var button = el("button", "history-item");
      button.type = "button";
      if (item.id === state.currentId) button.setAttribute("aria-current", "true");
      button.appendChild(el("span", "history-goal", item.goal));
      var meta = el("span", "history-meta");
      var badge = el("span");
      setBadge(badge, item.status);
      meta.appendChild(badge);
      meta.appendChild(
        el("span", "", formatTime(item.created_at) + " · " + formatElapsed(item.elapsed_seconds))
      );
      button.appendChild(meta);
      button.addEventListener("click", function () {
        selectRun(item.id);
      });
      row.appendChild(button);
      els.history.appendChild(row);
    });
  }

  function refreshHistory() {
    return api("/api/runs")
      .then(renderHistory)
      .catch(function () {
        // The list is a convenience. A failure here must not hide the run.
      });
  }

  // ---------- Polling and actions ----------

  function stopPolling() {
    if (state.pollTimer !== null) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
    state.pollFailures = 0;
  }

  function poll(id) {
    api("/api/runs/" + encodeURIComponent(id))
      .then(function (view) {
        if (state.currentId !== id) return;
        state.pollFailures = 0;
        renderRun(view);
        refreshHistory();
        if (view.status === "running") {
          state.pollTimer = setTimeout(function () {
            poll(id);
          }, POLL_MS);
        } else {
          state.pollTimer = null;
        }
      })
      .catch(function (error) {
        if (state.currentId !== id) return;
        if (error instanceof ApiError && error.status === 404) {
          showBanner("That run is no longer available. The server may have restarted.", "Run not found. ", true);
          stopPolling();
          return;
        }
        state.pollFailures += 1;
        if (state.pollFailures >= MAX_POLL_FAILURES) {
          showBanner("Reload the page, or select the run from Recent runs.", "Lost contact with the server. ", true);
          stopPolling();
          return;
        }
        state.pollTimer = setTimeout(function () {
          poll(id);
        }, POLL_MS * 2);
      });
  }

  function selectRun(id) {
    stopPolling();
    if (!state.setupBannerShown) hideBanner();
    state.currentId = id;
    state.renderedResultFor = null;
    history.replaceState(null, "", "#run=" + encodeURIComponent(id));
    poll(id);
  }

  function setSubmitting(value) {
    state.submitting = value;
    els.runButton.disabled = value;
    els.runButton.querySelector("span").textContent = value ? "Starting" : "Run goal";
  }

  function updateCounter() {
    var length = els.goal.value.length;
    els.counter.textContent = length + " / " + state.maxGoalChars;
    els.counter.classList.toggle("over", length > state.maxGoalChars);
  }

  function autoGrow() {
    els.goal.style.height = "auto";
    els.goal.style.height = Math.min(els.goal.scrollHeight + 2, 340) + "px";
  }

  function submit() {
    if (state.submitting) return;
    var goal = els.goal.value.trim();
    if (!goal) {
      showBanner("Write a goal first.", "", false);
      els.goal.focus();
      return;
    }
    if (goal.length > state.maxGoalChars) {
      showBanner("Shorten it to " + state.maxGoalChars + " characters or fewer.", "Goal is too long. ", true);
      return;
    }
    hideBanner();
    setSubmitting(true);
    api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: goal })
    })
      .then(function (view) {
        stopPolling();
        state.currentId = view.id;
        state.renderedResultFor = null;
        history.replaceState(null, "", "#run=" + encodeURIComponent(view.id));
        renderRun(view);
        refreshHistory();
        state.pollTimer = setTimeout(function () {
          poll(view.id);
        }, POLL_MS);
        els.runPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      })
      .catch(function (error) {
        if (error instanceof ApiError) {
          showBanner(error.message, error.status === 503 ? "Setup needed. " : "Could not start. ", true);
          if (error.status === 503) loadStatus();
        } else {
          showBanner("Check that the server is running, then try again.", "Could not reach the server. ", true);
        }
      })
      .then(function () {
        setSubmitting(false);
      });
  }

  function loadStatus() {
    return api("/api/status")
      .then(function (status) {
        state.maxGoalChars = status.max_goal_chars;
        updateCounter();
        els.version.textContent = "Version " + status.version;
        if (status.ready) {
          els.pill.className = "pill pill-ok";
          els.pill.textContent = status.llm_model + " · " + status.search_provider;
          els.pill.title = "Model provider: " + status.llm_provider;
          if (state.setupBannerShown) {
            state.setupBannerShown = false;
            hideBanner();
          }
        } else {
          state.setupBannerShown = true;
          els.pill.className = "pill pill-bad";
          els.pill.textContent = "Setup needed";
          els.pill.title = status.problem || "";
          showBanner(
            (status.problem || "Configuration is incomplete.") + " Fix your .env file. It is read on each run.",
            "Setup needed. ",
            false
          );
        }
      })
      .catch(function () {
        els.pill.className = "pill pill-bad";
        els.pill.textContent = "Server unreachable";
      });
  }

  // ---------- Setup ----------

  function setupExamples() {
    EXAMPLES.forEach(function (text) {
      var chip = el("button", "chip", text);
      chip.type = "button";
      chip.addEventListener("click", function () {
        els.goal.value = text;
        updateCounter();
        autoGrow();
        els.goal.focus();
      });
      els.examples.appendChild(chip);
    });
  }

  function currentTheme() {
    var set = document.documentElement.dataset.theme;
    if (set === "light" || set === "dark") return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function toggleTheme() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (error) {
      // Storage can be blocked. The theme still changes for this visit.
    }
  }

  function copyOutput() {
    if (!state.lastOutput) return;
    var original = els.copy.textContent;
    var finish = function (text) {
      els.copy.textContent = text;
      setTimeout(function () {
        els.copy.textContent = original;
      }, 1600);
    };
    if (!navigator.clipboard) {
      finish("Copy not available");
      return;
    }
    navigator.clipboard.writeText(state.lastOutput).then(
      function () {
        finish("Copied");
      },
      function () {
        finish("Copy failed");
      }
    );
  }

  function downloadOutput() {
    if (!state.lastOutput) return;
    var blob = new Blob([state.lastOutput], { type: "text/markdown;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "research-" + state.currentId + ".md";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function runFromHash() {
    var match = /^#run=([\w-]+)$/.exec(location.hash);
    if (match) {
      selectRun(match[1]);
    } else {
      stopPolling();
      state.currentId = null;
      clearRunView();
    }
  }

  els.form.addEventListener("submit", function (event) {
    event.preventDefault();
    submit();
  });
  els.goal.addEventListener("input", function () {
    updateCounter();
    autoGrow();
  });
  els.goal.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submit();
    }
  });
  els.retry.addEventListener("click", function () {
    els.goal.focus();
    els.goal.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  els.copy.addEventListener("click", copyOutput);
  els.download.addEventListener("click", downloadOutput);
  els.theme.addEventListener("click", toggleTheme);
  window.addEventListener("hashchange", runFromHash);
  window.addEventListener("focus", loadStatus);

  setupExamples();
  updateCounter();
  loadStatus().then(function () {
    refreshHistory();
    runFromHash();
  });
})();
