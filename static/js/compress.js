/*
 * Сжатие фотографий перед отправкой.
 *
 * Снимок страницы с телефона весит 3–5 МБ, а предел для файлов
 * школьников — 2 МБ. Поэтому фото уменьшаем прямо в браузере: длинная
 * сторона до 2000 px и JPEG — текст на такой картинке читается
 * свободно, а весит она 0,5–1 МБ. PDF и код не трогаем, только
 * заранее предупреждаем, если файл больше предела.
 *
 * Подключается к полям <input type="file" data-max-mb="2">. Если
 * браузер чего-то не умеет, файл уходит как есть, а размер проверит
 * сервер — страница от этого не ломается.
 */
(function () {
  var MAX_SIDE = 2000;
  var IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

  function loadImage(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("не картинка")); };
      img.src = url;
    });
  }

  function toBlob(canvas, quality) {
    return new Promise(function (resolve) { canvas.toBlob(resolve, "image/jpeg", quality); });
  }

  async function shrink(file, limit) {
    var img = await loadImage(file);
    var scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
    var canvas = document.createElement("canvas");
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";  // прозрачный PNG не должен стать чёрным
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    var blob = null;
    for (var q = 0.85; q >= 0.45; q -= 0.1) {
      blob = await toBlob(canvas, q);
      if (blob && blob.size <= limit) break;
    }
    if (!blob || blob.size >= file.size) return file;
    var name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: Date.now() });
  }

  function mb(bytes) { return (bytes / 1024 / 1024).toFixed(1).replace(".", ","); }

  function note(input, text, isError) {
    var el = input.parentNode.querySelector(".upload-note");
    if (!el) {
      el = document.createElement("span");
      el.className = "helptext upload-note";
      input.insertAdjacentElement("afterend", el);
    }
    el.textContent = text;
    el.classList.toggle("upload-note-error", !!isError);
  }

  async function handle(input) {
    var limitMb = parseFloat(input.dataset.maxMb);
    var limit = limitMb * 1024 * 1024;
    var files = Array.prototype.slice.call(input.files || []);
    if (!files.length || !window.DataTransfer) return true;

    var form = input.form;
    var submit = form && form.querySelector("[type=submit]");
    if (submit) submit.disabled = true;
    note(input, "Готовлю файлы…");

    var out = new DataTransfer();
    var tooBig = [];
    var shrunk = 0;
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      if (f.size > limit * 0.9 && IMAGE_TYPES.indexOf(f.type) !== -1) {
        try {
          var small = await shrink(f, limit * 0.9);
          if (small !== f) shrunk++;
          f = small;
        } catch (e) { /* оставим как есть, проверит сервер */ }
      }
      if (f.size > limit) tooBig.push(f.name + " (" + mb(f.size) + " МБ)");
      out.items.add(f);
    }
    input.files = out.files;
    if (submit) submit.disabled = false;

    if (tooBig.length) {
      note(input, "Больше " + limitMb + " МБ: " + tooBig.join(", ") +
           ". Сохраните PDF в меньшем качестве или загрузите страницы фотографиями.", true);
      return false;
    }
    note(input, shrunk ? "Фото уменьшены для отправки: " + shrunk + " шт." : "");
    return true;
  }

  document.addEventListener("change", function (event) {
    var input = event.target;
    if (input.matches && input.matches("input[type=file][data-max-mb]")) handle(input);
  });

  // Второй рубеж: не отправляем форму с заведомо слишком большим файлом —
  // иначе школьник ждёт загрузку 20 МБ по мобильному, чтобы получить отказ.
  document.addEventListener("submit", function (event) {
    var inputs = event.target.querySelectorAll("input[type=file][data-max-mb]");
    for (var i = 0; i < inputs.length; i++) {
      var limit = parseFloat(inputs[i].dataset.maxMb) * 1024 * 1024;
      var files = inputs[i].files || [];
      for (var j = 0; j < files.length; j++) {
        if (files[j].size > limit) {
          event.preventDefault();
          note(inputs[i], "Файл «" + files[j].name + "» больше " + inputs[i].dataset.maxMb +
               " МБ — такой не примут.", true);
          return;
        }
      }
    }
  }, true);
})();
