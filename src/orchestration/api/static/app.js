(function () {
  "use strict";

  var POLL_MS = 1000;
  var MAX_POLL_FAILURES = 5;
  var BASE_TITLE = "Multi-Agent Orchestration";
  var EXAMPLES = [
    {
      label: "Tech events",
      text: "Research upcoming technology events and summarize the useful findings with sources."
    },
    {
      label: "Local LLM tools",
      text: "Compare the main open-source tools for running large language models locally."
    },
    {
      label: "Energy storage",
      text: "Summarize recent news about renewable energy storage, with sources."
    }
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
    prompt: document.querySelector(".prompt-box"),
    goal: $("goal"),
    counter: $("counter"),
    runButton: $("run-button"),
    examples: $("examples"),
    banner: $("banner"),
    empty: $("empty-state"),
    runPanel: $("run-panel"),
    runKicker: $("run-kicker"),
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
    theme: $("theme-toggle"),
    activity: $("activity")
  };

  var state = {
    maxGoalChars: 2000,
    currentId: null,
    pollTimer: null,
    pollFailures: 0,
    renderedResultFor: null,
    lastOutput: "",
    submitting: false,
    setupBannerShown: false,
    ready: false,
    copyTimer: null,
    scrollOnNext: false
  };

  var clock = { timer: null, base: 0, mark: 0 };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function prefersMotion() {
    return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function scrollToNode(node, block) {
    node.scrollIntoView({ behavior: prefersMotion() ? "smooth" : "auto", block: block || "start" });
  }

  function show(node) {
    if (!node.hidden) return;
    node.hidden = false;
    node.classList.remove("rise");
    void node.offsetWidth;
    node.classList.add("rise");
  }

  function hide(node) {
    node.hidden = true;
    node.classList.remove("rise");
  }

  function nudge(node) {
    node.classList.remove("nudge");
    void node.offsetWidth;
    node.classList.add("nudge");
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

  function stopClock() {
    if (clock.timer !== null) {
      clearInterval(clock.timer);
      clock.timer = null;
    }
  }

  function paintElapsed() {
    els.runElapsed.textContent = formatElapsed(clock.base + (performance.now() - clock.mark) / 1000);
  }

  function syncClock(view) {
    if (view.status !== "running") {
      stopClock();
      els.runElapsed.textContent = formatElapsed(view.elapsed_seconds);
      return;
    }
    clock.base = view.elapsed_seconds;
    clock.mark = performance.now();
    paintElapsed();
    if (clock.timer === null) clock.timer = setInterval(paintElapsed, 1000);
  }

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

  function setBadge(node, value) {
    var next = "badge badge-" + value;
    if (node.className === next && node.textContent === value) return;
    node.className = next;
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

  function stepStateAt(view, index) {
    var failed = view.status === "failed";
    var done = view.status === "done";
    var active = failed ? failedStepIndex(view) : STAGE_STEP[view.stage];
    if (done || index < active) return "done";
    if (index === active) return failed ? "failed" : "active";
    return "pending";
  }

  function noteFor(step, stepState, view) {
    if (stepState === "failed") return "Stopped here";
    if (stepState === "active" && view.stage === "revise" && step.key === "research") return "Revising";
    if (stepState === "active" && view.stage === "finalize" && step.key === "final") return "Writing";
    return step.note;
  }

  function renderStepper(view) {
    var key = STEPS.map(function (step, index) {
      return stepStateAt(view, index);
    }).join(",") + ":" + view.stage;
    if (els.stepper.dataset.key === key) return;
    els.stepper.dataset.key = key;
    clear(els.stepper);
    STEPS.forEach(function (step, index) {
      var stepState = stepStateAt(view, index);
      var item = el("li", "step");
      item.dataset.state = stepState;
      item.appendChild(el("div", "step-mark", String(index + 1)));
      var copy = el("div");
      copy.appendChild(el("div", "step-name", step.name));
      copy.appendChild(el("div", "step-note", noteFor(step, stepState, view)));
      item.appendChild(copy);
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
    var key = view.tasks.map(function (task) {
      return [task.id, task.status, task.attempts, task.error || "", task.description].join("\u0001");
    }).join("\u0002");
    els.tasksBlock.hidden = view.tasks.length === 0;
    els.tasksCount.textContent = view.tasks.length ? "(" + view.tasks.length + ")" : "";
    if (els.tasks.dataset.key === key) return;
    els.tasks.dataset.key = key;
    clear(els.tasks);
    view.tasks.forEach(function (task) {
      var row = el("li", "task");
      row.dataset.status = task.status;
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
    var key = review ? review.verdict + "\u0001" + review.revision_count + "\u0001" + review.issues.join("\u0002") : "";
    els.reviewBlock.hidden = !review;
    if (!review || els.reviewBlock.dataset.key === key) return;
    els.reviewBlock.dataset.key = key;
    setBadge(els.reviewVerdict, review.verdict);
    els.reviewRevisions.textContent = review.revision_count > 0 ? "Revisions used: " + review.revision_count : "";
    clear(els.reviewIssues);
    review.issues.forEach(function (issue) {
      els.reviewIssues.appendChild(el("li", "", issue));
    });
  }

  function renderErrors(view) {
    var failed = view.status === "failed";
    var hasErrors = view.errors.length > 0;
    var visible = hasErrors || failed;
    var key = (visible ? "1" : "0") + "\u0001" + (failed ? "1" : "0") + "\u0001" + view.errors.join("\u0002");
    els.errorsBlock.hidden = !visible;
    if (!visible || els.errorsBlock.dataset.key === key) return;
    els.errorsBlock.dataset.key = key;
    els.errorsBlock.querySelector(".section-title").textContent = failed ? "What went wrong" : "Problems so far";
    clear(els.errors);
    var messages = hasErrors ? view.errors : ["The run did not finish. No details were recorded."];
    messages.forEach(function (message) {
      els.errors.appendChild(el("li", "", message));
    });
    els.retry.hidden = !failed;
  }

  function renderResult(view) {
    var ready = view.status === "done" && !!view.final_output;
    if (!ready) {
      hide(els.resultPanel);
      state.renderedResultFor = null;
      state.lastOutput = "";
      return;
    }
    var first = state.renderedResultFor !== view.id;
    show(els.resultPanel);
    if (!first) return;
    renderMarkdown(view.final_output, els.resultBody);
    state.renderedResultFor = view.id;
    state.lastOutput = view.final_output;
    if (!state.scrollOnNext) scrollToNode(els.resultPanel, "nearest");
  }

  function setWorking(on) {
    if (els.activity.hidden === on) els.activity.hidden = !on;
  }

  function renderRun(view) {
    hide(els.empty);
    show(els.runPanel);
    els.runPanel.dataset.status = view.status;
    els.runKicker.textContent = view.id ? "Run" : "Starting";
    if (els.runId.textContent !== view.id) els.runId.textContent = view.id;
    if (els.runTitle.textContent !== view.goal) els.runTitle.textContent = view.goal;
    setBadge(els.runBadge, view.status);
    syncClock(view);
    renderStepper(view);
    var caption = captionFor(view);
    if (els.caption.textContent !== caption) els.caption.textContent = caption;
    renderTasks(view);
    renderReview(view);
    renderErrors(view);
    renderResult(view);
    setWorking(view.status === "running");
    markCurrent();
    if (state.scrollOnNext) {
      state.scrollOnNext = false;
      scrollToNode(view.status === "done" && view.final_output ? els.resultPanel : els.runPanel, "start");
    }

    if (view.status === "running") document.title = "Running · " + BASE_TITLE;
    else if (view.status === "done") document.title = "Done · " + BASE_TITLE;
    else document.title = "Failed · " + BASE_TITLE;
  }

  function clearRunView() {
    stopClock();
    hide(els.runPanel);
    hide(els.resultPanel);
    show(els.empty);
    setWorking(false);
    state.renderedResultFor = null;
    document.title = BASE_TITLE;
    markCurrent();
  }

  function historyKey(items) {
    return items.map(function (item) {
      return item.id + "\t" + item.status + "\t" + item.goal;
    }).join("\n");
  }

  function historyStamp(item) {
    return formatTime(item.created_at) + " · " + formatElapsed(item.elapsed_seconds);
  }

  function updateHistoryTimes(items) {
    var rows = els.history.querySelectorAll(".history-item");
    items.forEach(function (item) {
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].dataset.id !== item.id) continue;
        var time = rows[i].querySelector(".history-time");
        var stamp = historyStamp(item);
        if (time && time.textContent !== stamp) time.textContent = stamp;
      }
    });
  }

  function markCurrent() {
    var rows = els.history.querySelectorAll(".history-item");
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].dataset.id === state.currentId) rows[i].setAttribute("aria-current", "true");
      else rows[i].removeAttribute("aria-current");
    }
  }

  function renderHistory(items) {
    els.historyEmpty.hidden = items.length > 0;
    var key = historyKey(items);
    if (els.history.dataset.key === key) {
      updateHistoryTimes(items);
      markCurrent();
      return;
    }
    els.history.dataset.key = key;
    clear(els.history);
    items.forEach(function (item) {
      var row = el("li");
      var button = el("button", "history-item");
      button.type = "button";
      button.dataset.id = item.id;
      button.appendChild(el("span", "history-goal", item.goal));
      var meta = el("span", "history-meta");
      var badge = el("span");
      setBadge(badge, item.status);
      meta.appendChild(badge);
      meta.appendChild(el("span", "history-time", historyStamp(item)));
      button.appendChild(meta);
      button.addEventListener("click", function () {
        selectRun(item.id);
      });
      row.appendChild(button);
      els.history.appendChild(row);
    });
    markCurrent();
  }

  function refreshHistory() {
    return api("/api/runs")
      .then(renderHistory)
      .catch(function () {
        // The list is a convenience. A failure here must not hide the run.
      });
  }

  function stopPolling() {
    if (state.pollTimer !== null) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
    state.pollFailures = 0;
    stopClock();
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
    state.scrollOnNext = true;
    markCurrent();
    history.replaceState(null, "", "#run=" + encodeURIComponent(id));
    poll(id);
  }

  function setSubmitting(value) {
    state.submitting = value;
    els.runButton.disabled = value;
    els.runButton.classList.toggle("is-busy", value);
    els.runButton.setAttribute("aria-busy", value ? "true" : "false");
    els.runButton.querySelector("span").textContent = value ? "Starting" : "Run";
  }

  function updateCounter() {
    var length = els.goal.value.length;
    var max = state.maxGoalChars;
    els.counter.textContent = length + " / " + max;
    els.counter.classList.toggle("near", length > max * 0.85 && length <= max);
    els.counter.classList.toggle("over", length > max);
    els.goal.setAttribute("aria-invalid", length > max ? "true" : "false");
    var chips = els.examples.querySelectorAll(".chip");
    for (var i = 0; i < chips.length; i++) {
      chips[i].setAttribute("aria-pressed", chips[i].dataset.text === els.goal.value ? "true" : "false");
    }
  }

  function autoGrow() {
    els.goal.style.height = "auto";
    els.goal.style.height = Math.min(els.goal.scrollHeight + 2, 320) + "px";
  }

  function showStartError(error) {
    if (error instanceof ApiError) {
      showBanner(error.message, error.status === 503 ? "Setup needed. " : "Could not start. ", true);
      if (error.status === 503) loadStatus();
    } else {
      showBanner("Check that the server is running, then try again.", "Could not reach the server. ", true);
    }
  }

  function submit() {
    if (state.submitting) return;
    var goal = els.goal.value.trim();
    if (!goal) {
      showBanner("Write a goal first.", "", false);
      nudge(els.prompt);
      els.goal.focus();
      return;
    }
    if (goal.length > state.maxGoalChars) {
      showBanner("Shorten it to " + state.maxGoalChars + " characters or fewer.", "Goal is too long. ", true);
      nudge(els.prompt);
      els.goal.focus();
      return;
    }
    if (!state.setupBannerShown) hideBanner();
    var previousId = state.currentId;
    setSubmitting(true);
    stopPolling();
    state.currentId = "pending";
    state.renderedResultFor = null;
    state.lastOutput = "";
    markCurrent();
    if (state.ready) {
      renderRun({
        id: "",
        goal: goal,
        status: "running",
        stage: "plan",
        elapsed_seconds: 0,
        tasks: [],
        review: null,
        errors: [],
        final_output: null
      });
      scrollToNode(els.runPanel, "start");
    }
    api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: goal })
    })
      .then(function (view) {
        refreshHistory();
        if (state.currentId !== "pending") return;
        state.currentId = view.id;
        state.renderedResultFor = null;
        history.replaceState(null, "", "#run=" + encodeURIComponent(view.id));
        renderRun(view);
        state.pollTimer = setTimeout(function () {
          poll(view.id);
        }, POLL_MS);
      })
      .catch(function (error) {
        if (state.currentId === "pending") {
          if (previousId && previousId !== "pending") {
            selectRun(previousId);
          } else {
            state.currentId = null;
            clearRunView();
            history.replaceState(null, "", location.pathname + location.search);
          }
        }
        showStartError(error);
      })
      .then(function () {
        setSubmitting(false);
      });
  }

  function loadStatus() {
    return api("/api/status")
      .then(function (status) {
        state.maxGoalChars = status.max_goal_chars;
        state.ready = status.ready;
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
        state.ready = false;
        els.pill.className = "pill pill-bad";
        els.pill.textContent = "Server unreachable";
      });
  }

  function setupExamples() {
    EXAMPLES.forEach(function (item) {
      var chip = el("button", "chip", item.label);
      chip.type = "button";
      chip.dataset.text = item.text;
      chip.title = item.text;
      chip.setAttribute("aria-label", item.text);
      chip.addEventListener("click", function () {
        els.goal.value = item.text;
        updateCounter();
        autoGrow();
        els.goal.focus();
        els.goal.setSelectionRange(item.text.length, item.text.length);
      });
      els.examples.appendChild(chip);
    });
  }

  function currentTheme() {
    var set = document.documentElement.dataset.theme;
    if (set === "light" || set === "dark") return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyThemeLabel() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    var label = "Switch to " + next + " theme";
    els.theme.setAttribute("aria-label", label);
    els.theme.title = label;
  }

  function toggleTheme() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (error) {
      // Storage can be blocked. The theme still changes for this visit.
    }
    applyThemeLabel();
  }

  function copyOutput() {
    if (!state.lastOutput) return;
    var label = els.copy.querySelector("span");
    var finish = function (text) {
      label.textContent = text;
      els.copy.classList.toggle("is-done", text === "Copied");
      if (state.copyTimer !== null) clearTimeout(state.copyTimer);
      state.copyTimer = setTimeout(function () {
        label.textContent = label.dataset.label || "Copy";
        els.copy.classList.remove("is-done");
        state.copyTimer = null;
      }, 1400);
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

  function setupShortcut() {
    var mac = /Mac|iPhone|iPad/.test(navigator.platform) || /Mac/.test(navigator.userAgent);
    if (mac) $("mod-key").textContent = "⌘";
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
    scrollToNode(els.goal, "center");
  });
  els.copy.addEventListener("click", copyOutput);
  els.download.addEventListener("click", downloadOutput);
  els.theme.addEventListener("click", toggleTheme);
  window.addEventListener("hashchange", runFromHash);
  window.addEventListener("focus", loadStatus);

  setupShortcut();
  setupExamples();
  updateCounter();
  applyThemeLabel();
  loadStatus().then(function () {
    refreshHistory();
    runFromHash();
    if (!location.hash && document.activeElement === document.body) {
      els.goal.focus({ preventScroll: true });
    }
  });
})();
