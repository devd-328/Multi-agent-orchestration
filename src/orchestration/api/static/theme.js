// Applies the saved color theme before the page paints, so it does not flash.
(function () {
  try {
    var saved = localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.dataset.theme = saved;
    }
  } catch (error) {
    // Storage can be blocked. The system theme still applies.
  }
})();
