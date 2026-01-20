document.addEventListener("DOMContentLoaded", () => {
  const toast = document.getElementById("toast");

  if (!toast) return;

  const message = toast.textContent.trim();

  if (message.length > 0) {
    toast.classList.add("show");

    setTimeout(() => {
      toast.classList.remove("show");
    }, 2600);
  }
});
