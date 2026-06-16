// ===== KEYBOARD SHORTCUTS =====
document.addEventListener("keydown", e => {
  // Enter in task command input
  const taskCmdEl = document.getElementById("taskCmd");
  if (e.key === "Enter" && document.activeElement === taskCmdEl) {
    submitTask();
  }
  // Enter in recall query input
  const recallEl = document.getElementById("recallQuery");
  if (e.key === "Enter" && document.activeElement === recallEl) {
    runRecall();
  }
});

