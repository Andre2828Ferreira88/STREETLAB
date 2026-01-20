
  const sizeButtons = document.querySelectorAll(".option");
  const sizeInput = document.getElementById("selectedSize");
  const addToCartBtn = document.getElementById("addToCartBtn");

  sizeButtons.forEach(button => {
    button.addEventListener("click", () => {
      if (button.classList.contains("disabled")) return;

      // remove seleção anterior
      sizeButtons.forEach(b => b.classList.remove("active"));

      // marca o selecionado
      button.classList.add("active");

      // seta tamanho
      sizeInput.value = button.dataset.size;

      // 🔥 ativa botão de verdade
      addToCartBtn.disabled = false;
      addToCartBtn.classList.remove("btn--disabled");
    });
  });



