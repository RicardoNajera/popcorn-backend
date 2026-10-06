cat << 'EOF' > ~/Desktop/simulador_tv.html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Popcorn TV - Directo</title>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <style>
    :root {
      --bg: #090b10;
      --card-bg: #141822;
      --accent: #ff3366;
      --accent-glow: rgba(255, 51, 102, 0.45);
      --text: #ffffff;
      --text-muted: #8b99ad;
      --card-w: 165px;
      --card-h: 245px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      overflow-x: hidden;
      user-select: none;
    }
    header {
      padding: 16px 48px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(9, 11, 16, 0.95);
      position: sticky;
      top: 0;
      z-index: 100;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      backdrop-filter: blur(10px);
    }
    .brand {
      font-size: 24px;
      font-weight: 900;
      color: var(--accent);
      letter-spacing: 1.5px;
    }
    .status-badge {
      font-size: 13px;
      font-weight: 600;
      color: #00ff88;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .status-badge::before {
      content: "";
      width: 8px;
      height: 8px;
      background: #00ff88;
      border-radius: 50%;
      box-shadow: 0 0 8px #00ff88;
    }
    #container {
      padding: 24px 48px 100px 48px;
      display: flex;
      flex-direction: column;
      gap: 36px;
    }
    .row-title {
      font-size: 22px;
      font-weight: 800;
      margin-bottom: 12px;
      color: #f1f5f9;
      letter-spacing: 0.5px;
    }
    .carousel {
      display: flex;
      gap: 16px;
      overflow-x: auto;
      scroll-behavior: smooth;
      padding: 12px 6px;
    }
    .carousel::-webkit-scrollbar { display: none; }
    .card {
      width: var(--card-w);
      min-width: var(--card-w);
      height: var(--card-h);
      background: var(--card-bg);
      border-radius: 10px;
      overflow: hidden;
      position: relative;
      outline: 3px solid transparent;
      transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), outline-color 0.2s, box-shadow 0.2s;
      cursor: pointer;
    }
    .card img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      background: #181d28;
    }
    .card .title-overlay {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      background: linear-gradient(0deg, rgba(0, 0, 0, 0.95) 0%, rgba(0, 0, 0, 0.6) 70%, transparent 100%);
      padding: 18px 10px 10px 10px;
      font-size: 13px;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      text-align: center;
    }
    .card.focused, .card:hover {
      transform: scale(1.08);
      outline-color: var(--accent);
      box-shadow: 0 12px 35px var(--accent-glow);
      z-index: 10;
    }
    #quality-modal {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.85);
      z-index: 200;
      justify-content: center;
      align-items: center;
      backdrop-filter: blur(10px);
    }
    .modal-box {
      background: #151922;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 14px;
      padding: 30px;
      width: 90%;
      max-width: 450px;
      text-align: center;
    }
    .modal-box h3 { font-size: 22px; margin-bottom: 8px; }
    .modal-box p { color: var(--text-muted); font-size: 14px; margin-bottom: 22px; }
    .options-list { display: flex; flex-direction: column; gap: 12px; max-height: 260px; overflow-y: auto; }
    .opt-btn {
      background: #202636;
      color: #fff;
      border: 1px solid rgba(255, 255, 255, 0.08);
      padding: 14px;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
    }
    .opt-btn:hover { background: var(--accent); }
    #player-modal {
      display: none;
      position: fixed;
      inset: 0;
      background: #000;
      z-index: 300;
      flex-direction: column;
      justify-content: center;
      align-items: center;
    }
    #player-modal video { width: 100%; height: 100%; outline: none; }
    .close-btn {
      position: absolute;
      top: 24px;
      right: 32px;
      background: rgba(0, 0, 0, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.3);
      color: #fff;
      padding: 10px 20px;
      border-radius: 30px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      z-index: 310;
    }
    .close-btn:hover { background: var(--accent); }
    .loading-msg {
      padding: 100px 0;
      text-align: center;
      color: var(--text-muted);
      font-size: 18px;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">POPCORN TV</div>
    <div class="status-badge" id="status-badge">En Línea</div>
  </header>

  <main id="container">
    <div class="loading-msg" id="loading-msg">Cargando cartelera principal...</div>
  </main>

  <div id="quality-modal">
    <div class="modal-box">
      <h3 id="modal-title">Título</h3>
      <p>Selecciona una opción de reproducción:</p>
      <div class="options-list" id="options-list"></div>
    </div>
  </div>

  <div id="player-modal">
    <button class="close-btn" onclick="cerrarReproductor()">✕ Salir (ESC)</button>
    <video id="tv-video" controls autoplay></video>
  </div>

  <script>
    const API_URL = "https://synapse-stream-api.onrender.com";
    let rowsData = [];
    let currentRow = 0;
    let currentCol = 0;
    let hlsInstance = null;

    const container = document.getElementById("container");
    const loadingMsg = document.getElementById("loading-msg");
    const qualityModal = document.getElementById("quality-modal");
    const optionsList = document.getElementById("options-list");
    const modalTitle = document.getElementById("modal-title");
    const playerModal = document.getElementById("player-modal");
    const tvVideo = document.getElementById("tv-video");

    async function cargarDirecto() {
      try {
        const res = await fetch(`${API_URL}/api/buscar`);
        const data = await res.json();

        if (Array.isArray(data) && data.length > 0) {
          rowsData = data;
          loadingMsg.style.display = "none";
          renderRows();
          updateFocus();
        }
      } catch (err) {
        loadingMsg.textContent = "Error al conectar con Render.";
      }
    }

    function renderRows() {
      container.innerHTML = "";
      rowsData.forEach((row, rIdx) => {
        const rowEl = document.createElement("div");
        rowEl.className = "row";

        const title = document.createElement("h2");
        title.className = "row-title";
        title.textContent = row.tituloFila;
        rowEl.appendChild(title);

        const carousel = document.createElement("div");
        carousel.className = "carousel";

        (row.items || []).forEach((item, cIdx) => {
          const card = document.createElement("div");
          card.className = "card";
          card.id = `card-${rIdx}-${cIdx}`;

          const img = document.createElement("img");
          img.src = item.poster && item.poster.startsWith("http")
            ? item.poster
            : "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=300";
          img.alt = item.title || "";
          img.loading = "lazy";
          img.onerror = () => {
            img.src = "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=300";
          };

          const label = document.createElement("div");
          label.className = "title-overlay";
          label.textContent = item.title || "";

          card.appendChild(img);
          card.appendChild(label);

          card.onclick = () => {
            currentRow = rIdx;
            currentCol = cIdx;
            updateFocus();
            seleccionarObra(item);
          };

          carousel.appendChild(card);
        });

        rowEl.appendChild(carousel);
        container.appendChild(rowEl);
      });
    }

    function seleccionarObra(item) {
      if (!item) return;
      const opts = item.opciones || [];
      if (opts.length > 1) {
        modalTitle.textContent = item.title;
        optionsList.innerHTML = "";
        opts.forEach(op => {
          const btn = document.createElement("button");
          btn.className = "opt-btn";
          btn.textContent = op.label || "Reproducir";
          btn.onclick = () => {
            qualityModal.style.display = "none";
            reproducirVideo(op.url);
          };
          optionsList.appendChild(btn);
        });
        qualityModal.style.display = "flex";
      } else {
        reproducirVideo(opts.length === 1 ? opts[0].url : item.url);
      }
    }

    function reproducirVideo(url) {
      if (!url) return;
      if (hlsInstance) { hlsInstance.destroy(); hlsInstance = null; }

      if (url.includes(".m3u8")) {
        if (Hls.isSupported()) {
          hlsInstance = new Hls();
          hlsInstance.loadSource(url);
          hlsInstance.attachMedia(tvVideo);
        } else if (tvVideo.canPlayType('application/vnd.apple.mpegurl')) {
          tvVideo.src = url;
        }
      } else {
        tvVideo.src = url;
      }
      playerModal.style.display = "flex";
      tvVideo.play().catch(() => {});
    }

    function cerrarReproductor() {
      tvVideo.pause();
      tvVideo.src = "";
      if (hlsInstance) { hlsInstance.destroy(); hlsInstance = null; }
      playerModal.style.display = "none";
    }

    function updateFocus() {
      document.querySelectorAll(".card.focused").forEach(c => c.classList.remove("focused"));
      const target = document.getElementById(`card-${currentRow}-${currentCol}`);
      if (target) {
        target.classList.add("focused");
        target.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
      }
    }

    window.addEventListener("keydown", (e) => {
      if (playerModal.style.display === "flex") {
        if (e.key === "Escape" || e.key === "Backspace") {
          cerrarReproductor();
          e.preventDefault();
        }
        return;
      }
      if (qualityModal.style.display === "flex") {
        if (e.key === "Escape" || e.key === "Backspace") {
          qualityModal.style.display = "none";
          e.preventDefault();
        }
        return;
      }
      if (!rowsData.length) return;
      const totalRows = rowsData.length;
      const totalCols = rowsData[currentRow]?.items?.length || 0;

      if (e.key === "ArrowRight" && currentCol < totalCols - 1) {
        currentCol++; updateFocus(); e.preventDefault();
      } else if (e.key === "ArrowLeft" && currentCol > 0) {
        currentCol--; updateFocus(); e.preventDefault();
      } else if (e.key === "ArrowDown" && currentRow < totalRows - 1) {
        currentRow++;
        const max = rowsData[currentRow]?.items?.length || 0;
        if (currentCol >= max) currentCol = Math.max(0, max - 1);
        updateFocus(); e.preventDefault();
      } else if (e.key === "ArrowUp" && currentRow > 0) {
        currentRow--;
        const max = rowsData[currentRow]?.items?.length || 0;
        if (currentCol >= max) currentCol = Math.max(0, max - 1);
        updateFocus(); e.preventDefault();
      } else if (e.key === "Enter") {
        seleccionarObra(rowsData[currentRow]?.items?.[currentCol]);
        e.preventDefault();
      }
    });

    cargarDirecto();
  </script>
</body>
</html>
EOF
