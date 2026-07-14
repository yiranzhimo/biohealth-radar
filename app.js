(function () {
  const data = window.BHR_DATA;
  const state = {
    category: "All",
    query: "",
    sourceType: "All",
    evidenceLevel: "All",
    reviewStatus: "All",
    view: "cards"
  };

  const els = {
    updatedAt: document.querySelector("#updated-at"),
    metricTotal: document.querySelector("#metric-total"),
    metricPrimary: document.querySelector("#metric-primary"),
    metricReview: document.querySelector("#metric-review"),
    metricHigh: document.querySelector("#metric-high"),
    reviewInboxButton: document.querySelector("#review-inbox-button"),
    sourceCount: document.querySelector("#source-count"),
    sourceList: document.querySelector("#source-list"),
    sourceFilter: document.querySelector("#source-filter"),
    evidenceFilter: document.querySelector("#evidence-filter"),
    reviewFilter: document.querySelector("#review-filter"),
    searchInput: document.querySelector("#search-input"),
    feedCount: document.querySelector("#feed-count"),
    cardFeed: document.querySelector("#card-feed"),
    tableFeed: document.querySelector("#table-feed"),
    viewCards: document.querySelector("#view-cards"),
    viewTable: document.querySelector("#view-table"),
    themeTotal: document.querySelector("#theme-total"),
    themeList: document.querySelector("#theme-list"),
    reviewCount: document.querySelector("#review-count"),
    reviewList: document.querySelector("#review-list"),
    themeMap: document.querySelector("#theme-map")
  };

  function normalize(value) {
    return String(value || "").toLowerCase();
  }

  function evidenceClass(level) {
    return normalize(level);
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function getPrimaryCount() {
    return data.signals.filter((item) => ["Regulator", "Registry", "Paper"].includes(item.sourceType)).length;
  }

  function getFilteredSignals() {
    const query = normalize(state.query);
    return data.signals.filter((item) => {
      const categoryMatch = state.category === "All" || item.primaryCategory === state.category;
      const sourceMatch = state.sourceType === "All" || item.sourceType === state.sourceType;
      const evidenceMatch = state.evidenceLevel === "All" || item.evidenceLevel === state.evidenceLevel;
      const reviewMatch =
        state.reviewStatus === "All" ||
        (state.reviewStatus === "NeedsReview" && item.needsReview) ||
        (state.reviewStatus === "Reviewed" && !item.needsReview);
      const haystack = normalize(
        [
          item.title,
          item.entity,
          item.primaryCategory,
          item.subCategory,
          item.eventType,
          item.sourceType,
          item.sourceName,
          item.reliability,
          item.evidenceLevel,
          item.fact,
          item.report,
          item.inference,
          item.unknown,
          ...(item.themes || []),
          ...(item.tags || [])
        ].join(" ")
      );
      const queryMatch = !query || haystack.includes(query);
      return categoryMatch && sourceMatch && evidenceMatch && reviewMatch && queryMatch;
    });
  }

  function renderMetrics() {
    els.updatedAt.textContent = data.updatedAt;
    els.metricTotal.textContent = data.signals.length;
    els.metricPrimary.textContent = getPrimaryCount();
    els.metricReview.textContent = data.signals.filter((item) => item.needsReview).length;
    els.metricHigh.textContent = data.signals.filter((item) => item.evidenceLevel === "High").length;
  }

  function renderSources() {
    els.sourceCount.textContent = data.sources.length;
    els.sourceList.innerHTML = data.sources
      .map(
        (source) => `
          <article class="source-item">
            <strong>${escapeHtml(source.name)}</strong>
            <div class="source-meta">
              <span>${escapeHtml(source.type)} · ${escapeHtml(source.reliability)}</span>
              <span>${escapeHtml(source.cadence)}</span>
            </div>
          </article>
        `
      )
      .join("");
  }

  function renderCards(signals) {
    if (!signals.length) {
      els.cardFeed.innerHTML = '<div class="empty-state">没有匹配的 signal</div>';
      return;
    }

    els.cardFeed.innerHTML = signals
      .map(
        (item) => `
          <article class="signal-card" id="signal-${escapeHtml(item.id)}">
            <div class="signal-top">
              <div class="signal-title">
                <h3>${escapeHtml(item.title)}</h3>
                <p>${escapeHtml(item.entity)} · ${escapeHtml(item.subCategory)}</p>
              </div>
              <div class="signal-date">${escapeHtml(item.date)}</div>
            </div>

            <div class="badge-row">
              <span class="badge">${escapeHtml(item.primaryCategory)}</span>
              <span class="badge">${escapeHtml(item.eventType)}</span>
              <span class="badge ${evidenceClass(item.evidenceLevel)}">${escapeHtml(item.evidenceLevel)} evidence</span>
              <span class="badge ${evidenceClass(item.reliability)}">${escapeHtml(item.sourceType)}</span>
              ${item.needsReview ? '<span class="badge review">Needs review</span>' : '<span class="badge reviewed">Reviewed</span>'}
            </div>

            <div class="tag-row">
              ${(item.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}
            </div>

            <div class="evidence-grid">
              <div class="evidence-box">
                <span>Fact</span>
                <p>${escapeHtml(item.fact)}</p>
              </div>
              <div class="evidence-box">
                <span>Report</span>
                <p>${escapeHtml(item.report)}</p>
              </div>
              <div class="evidence-box">
                <span>Inference</span>
                <p>${escapeHtml(item.inference)}</p>
              </div>
              <div class="evidence-box">
                <span>Unknown</span>
                <p>${escapeHtml(item.unknown)}</p>
              </div>
            </div>

            <footer class="signal-footer">
              <span>${escapeHtml(item.sourceName)} · ${escapeHtml(item.reliability)} reliability</span>
              <a href="${escapeHtml(item.sourceUrl)}" target="_blank" rel="noreferrer">Source</a>
            </footer>
          </article>
        `
      )
      .join("");
  }

  function renderTable(signals) {
    if (!signals.length) {
      els.tableFeed.innerHTML = '<div class="empty-state">没有匹配的 signal</div>';
      return;
    }

    els.tableFeed.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Signal</th>
            <th>Category</th>
            <th>Source</th>
            <th>Evidence</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>
          ${signals
            .map(
              (item) => `
                <tr>
                  <td>${escapeHtml(item.date)}</td>
                  <td><strong>${escapeHtml(item.title)}</strong><br>${escapeHtml(item.entity)}</td>
                  <td>${escapeHtml(item.primaryCategory)}<br>${escapeHtml(item.subCategory)}</td>
                  <td>${escapeHtml(item.sourceType)}<br>${escapeHtml(item.sourceName)}</td>
                  <td>${escapeHtml(item.evidenceLevel)}<br>${escapeHtml(item.reliability)} reliability</td>
                  <td>${item.needsReview ? "Yes" : "No"}</td>
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    `;
  }

  function getThemeCounts(signals) {
    const counts = new Map();
    signals.forEach((item) => {
      (item.themes || []).forEach((theme) => counts.set(theme, (counts.get(theme) || 0) + 1));
    });
    return Array.from(counts, ([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  }

  function renderThemes(signals) {
    const themes = getThemeCounts(signals);
    const max = Math.max(1, ...themes.map((theme) => theme.count));
    els.themeTotal.textContent = themes.length;
    els.themeList.innerHTML = themes
      .slice(0, 8)
      .map(
        (theme) => `
          <div class="theme-item">
            <div>
              <strong>${escapeHtml(theme.name)}</strong>
              <div class="theme-bar"><span style="width:${Math.max(12, (theme.count / max) * 100)}%"></span></div>
            </div>
            <span>${theme.count}</span>
          </div>
        `
      )
      .join("");
    drawThemeMap(themes.slice(0, 10));
  }

  function drawThemeMap(themes) {
    const canvas = els.themeMap;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    if (!themes.length) {
      ctx.fillStyle = "#637373";
      ctx.font = "14px sans-serif";
      ctx.fillText("No theme data", 24, 36);
      return;
    }

    const palette = ["#147c72", "#3757a6", "#7a5c18", "#a33c3c", "#1f7a4d"];
    const max = Math.max(...themes.map((theme) => theme.count));
    themes.forEach((theme, index) => {
      const angle = (index / themes.length) * Math.PI * 2;
      const radius = 28 + (index % 4) * 22;
      const x = width / 2 + Math.cos(angle) * radius * 1.7;
      const y = height / 2 + Math.sin(angle) * radius;
      const size = 10 + (theme.count / max) * 20;

      ctx.beginPath();
      ctx.moveTo(width / 2, height / 2);
      ctx.lineTo(x, y);
      ctx.strokeStyle = "rgba(20, 124, 114, 0.18)";
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(x, y, size, 0, Math.PI * 2);
      ctx.fillStyle = palette[index % palette.length];
      ctx.globalAlpha = 0.88;
      ctx.fill();
      ctx.globalAlpha = 1;

      ctx.fillStyle = "#172121";
      ctx.font = "12px sans-serif";
      ctx.fillText(theme.name, Math.min(width - 120, x + size + 6), Math.max(16, y + 4));
    });

    ctx.beginPath();
    ctx.arc(width / 2, height / 2, 12, 0, Math.PI * 2);
    ctx.fillStyle = "#172121";
    ctx.fill();
  }

  function renderReviewQueue() {
    const reviewItems = data.signals.filter((item) => item.needsReview);
    els.reviewCount.textContent = reviewItems.length;
    els.reviewList.innerHTML = reviewItems
      .map(
        (item) => `
          <button class="review-item" data-signal-id="${escapeHtml(item.id)}" type="button">
            <strong>${escapeHtml(item.title)}</strong>
            <div class="review-meta">
              <span>${escapeHtml(item.sourceType)} · ${escapeHtml(item.evidenceLevel)}</span>
              <span>${escapeHtml(item.date)}</span>
            </div>
          </button>
        `
      )
      .join("");
  }

  function setActiveCategory(category) {
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.category === category);
    });
  }

  function syncControls() {
    els.searchInput.value = state.query;
    els.sourceFilter.value = state.sourceType;
    els.evidenceFilter.value = state.evidenceLevel;
    els.reviewFilter.value = state.reviewStatus;
    setActiveCategory(state.category);
  }

  function openReviewInbox() {
    state.category = "All";
    state.query = "";
    state.sourceType = "All";
    state.evidenceLevel = "All";
    state.reviewStatus = "NeedsReview";
    syncControls();
    renderFeed();
  }

  function focusSignal(signalId) {
    openReviewInbox();
    setView("cards");
    window.requestAnimationFrame(() => {
      const card = document.getElementById(`signal-${signalId}`);
      if (!card) return;
      card.scrollIntoView({ behavior: "smooth", block: "start" });
      card.classList.add("signal-card-highlight");
      window.setTimeout(() => card.classList.remove("signal-card-highlight"), 1800);
    });
  }

  function renderFeed() {
    const signals = getFilteredSignals();
    els.feedCount.textContent = `${signals.length} signals`;
    renderCards(signals);
    renderTable(signals);
    renderThemes(signals);
  }

  function setView(view) {
    state.view = view;
    const table = view === "table";
    els.cardFeed.classList.toggle("hidden", table);
    els.tableFeed.classList.toggle("hidden", !table);
    els.viewCards.classList.toggle("active", !table);
    els.viewTable.classList.toggle("active", table);
  }

  function bindEvents() {
    document.querySelectorAll(".nav-item").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        state.category = button.dataset.category;
        renderFeed();
      });
    });

    els.searchInput.addEventListener("input", (event) => {
      state.query = event.target.value;
      renderFeed();
    });

    els.sourceFilter.addEventListener("change", (event) => {
      state.sourceType = event.target.value;
      renderFeed();
    });

    els.evidenceFilter.addEventListener("change", (event) => {
      state.evidenceLevel = event.target.value;
      renderFeed();
    });

    els.reviewFilter.addEventListener("change", (event) => {
      state.reviewStatus = event.target.value;
      renderFeed();
    });

    els.reviewInboxButton.addEventListener("click", openReviewInbox);

    els.reviewList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-signal-id]");
      if (!button) return;
      focusSignal(button.dataset.signalId);
    });

    els.viewCards.addEventListener("click", () => setView("cards"));
    els.viewTable.addEventListener("click", () => setView("table"));
  }

  renderMetrics();
  renderSources();
  renderReviewQueue();
  renderFeed();
  bindEvents();
})();
