(function () {
  const data = window.BHR_DATA || { companies: [] };
  const intelligence = window.BHR_COMPANY_INTELLIGENCE || {
    profiles: [],
    candidates: [],
    summary: {}
  };
  const registryCompanies = data.companies || [];
  const profileByCompanyId = new Map(
    (intelligence.profiles || []).map((profile) => [profile.companyId, profile])
  );
  // The canonical registry remains a curated seed list. The directory must use
  // generated profiles as its source so automatically discovered companies are visible too.
  const companies = (intelligence.profiles || []).map((profile) => {
    const registry = registryCompanies.find((item) => item.id === profile.companyId) || {};
    return {
      ...registry,
      id: profile.companyId,
      name: profile.name || registry.name,
      ticker: profile.identity?.ticker || registry.ticker,
      headquarters: profile.identity?.headquarters || registry.headquarters,
      directions: profile.classification?.directions || registry.directions || [],
      modalities: profile.classification?.modalities || registry.modalities || [],
      aliases: registry.aliases || []
    };
  });
  const companyById = new Map(companies.map((company) => [company.id, company]));

  const chineseLabels = {
    "AI Drug Discovery": "人工智能药物发现",
    "Antibody / ADC": "抗体与抗体偶联药物",
    "Cell Therapy": "细胞治疗",
    "Gene Editing": "基因编辑",
    "Healthcare AI": "医疗人工智能",
    Immunotherapy: "免疫治疗",
    "Integrated Biopharma": "综合生物制药",
    Longevity: "长寿与衰老干预",
    Oncology: "肿瘤学",
    "Organoids & Disease Models": "类器官与疾病模型",
    "Precision Diagnostics": "精准诊断",
    "RNA Therapeutics": "RNA 疗法",
    "Sequencing & Research Tools": "测序与科研工具",
    "Targeted Protein Degradation": "靶向蛋白降解",
    AI: "人工智能",
    "Aging Biology": "衰老生物学",
    "Antibody Platform": "抗体平台",
    "Antisense Oligonucleotide": "反义寡核苷酸",
    Autophagy: "自噬",
    "Base Editing": "碱基编辑",
    Biologics: "生物制剂",
    "Bispecific Antibody": "双特异性抗体",
    "Cancer Screening": "癌症筛查",
    "Cell Programming": "细胞编程",
    "Cellular Rejuvenation": "细胞年轻化",
    "Cellular Reprogramming": "细胞重编程",
    "Clinical Data": "临床数据",
    "DNA Vaccine": "DNA 疫苗",
    "Disease Models": "疾病模型",
    "Drug Discovery": "药物发现",
    "E3 Ligase": "E3 连接酶",
    "Ex Vivo CRISPR": "体外 CRISPR 编辑",
    "Generative Chemistry": "生成式化学",
    "Genetic Testing": "基因检测",
    "Human Tissue Models": "人体组织模型",
    "In Vivo CAR-T": "体内 CAR-T",
    "In Vivo CRISPR": "体内 CRISPR 编辑",
    "In Vivo Editing": "体内编辑",
    "LNP Delivery": "脂质纳米颗粒递送",
    "Lab Automation": "实验室自动化",
    "Liquid Biopsy": "液体活检",
    "Long-read Sequencing": "长读长测序",
    "Molecular Diagnostics": "分子诊断",
    "Monoclonal Antibody": "单克隆抗体",
    "Multi-omics": "多组学",
    "Nanopore Sequencing": "纳米孔测序",
    "Organ-on-a-Chip": "器官芯片",
    Organoids: "类器官",
    "Patient-derived Organoids": "患者来源类器官",
    "Phenotypic Screening": "表型筛选",
    "Plasma Therapeutics": "血浆疗法",
    "Protein Degrader": "蛋白降解剂",
    "RNA Targeting": "RNA 靶向",
    "Regenerative Medicine": "再生医学",
    "Short-read Sequencing": "短读长测序",
    "Single Cell": "单细胞技术",
    "Small Molecule": "小分子药物",
    "Spatial Biology": "空间生物学",
    "Synthetic Biology": "合成生物学",
    "T Cell Programming": "T 细胞编程",
    "Target Discovery": "靶点发现",
    Therapeutics: "治疗药物",
    Vaccine: "疫苗",
    "Diagnostics / Research Tools": "诊断与科研工具",
    "Platform / Therapeutics": "平台与治疗药物",
    Paper: "论文",
    Filing: "监管申报",
    Registry: "注册数据库",
    Company: "公司官网",
    ClinicalTrials: "临床试验注册",
    NIH: "美国国立卫生研究院",
    SEC: "美国证券交易委员会",
    CSI: "中证指数",
    HKEX: "香港交易所",
    HSI: "恒生指数",
    High: "高",
    Medium: "中",
    Low: "低",
    Report: "来源自述",
    Unknown: "未知",
    "Medicinal Chemicals and Botanical Products": "药用化学品与植物制品",
    "Pharmaceutical Preparations": "药物制剂",
    "In Vitro and In Vivo Diagnostic Substances": "体外与体内诊断物质",
    "Biological Products, Except Diagnostic Substances": "生物制品（诊断制品除外）",
    biotechnology: "生物技术",
    "gene therapy": "基因治疗",
    "cell therapy": "细胞治疗",
    "drug discovery": "药物发现",
    "molecular diagnostics": "分子诊断"
  };
  const directionAliases = {
    "gene editing": "Gene Editing",
    "基因编辑": "Gene Editing",
    "ai drug discovery": "AI Drug Discovery",
    "人工智能药物发现": "AI Drug Discovery",
    "precision diagnostics": "Precision Diagnostics",
    "精准诊断": "Precision Diagnostics",
    "cell therapy": "Cell Therapy",
    "细胞治疗": "Cell Therapy",
    "rna therapeutics": "RNA Therapeutics",
    "rna 疗法": "RNA Therapeutics"
  };

  const initialHash = decodeURIComponent(window.location.hash.slice(1));
  const firstSupported = (intelligence.profiles || []).find(
    (profile) => profile.currentBusiness?.status === "company_reported"
  );
  const state = {
    query: "",
    direction: "All",
    region: "All",
    coverage: "All",
    reviewApiEnabled: false,
    reviewer: "",
    companyId: companyById.has(initialHash) ? initialHash : firstSupported?.companyId || companies[0]?.id || ""
  };

  const els = {
    updatedAt: document.querySelector("#updated-at"),
    metricCompanies: document.querySelector("#metric-companies"),
    metricSupported: document.querySelector("#metric-supported"),
    metricAutoReviewed: document.querySelector("#metric-auto-reviewed"),
    metricCandidates: document.querySelector("#metric-candidates"),
    metricBusinessCovered: document.querySelector("#metric-business-covered"),
    metricSourceFailures: document.querySelector("#metric-source-failures"),
    search: document.querySelector("#company-search"),
    direction: document.querySelector("#direction-filter"),
    region: document.querySelector("#region-filter"),
    coverage: document.querySelector("#coverage-filter"),
    directoryCount: document.querySelector("#directory-count"),
    companyList: document.querySelector("#company-list"),
    companyDetail: document.querySelector("#company-detail"),
    candidateCount: document.querySelector("#candidate-count"),
    candidateSummary: document.querySelector("#candidate-summary"),
    candidateList: document.querySelector("#candidate-list")
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function safeExternalUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "https:" ? url.href : "";
    } catch (_error) {
      return "";
    }
  }

  function normalize(value) {
    return String(value || "").toLocaleLowerCase();
  }

  function chineseLabel(value, fallback = "") {
    const text = String(value || fallback);
    return chineseLabels[text] || text;
  }

  function canonicalDirection(value) {
    const text = String(value || "").trim();
    return directionAliases[text.toLocaleLowerCase()] || text;
  }

  function companyRegion(company, profile) {
    const exchange = String(profile?.identity?.exchange || "").toUpperCase();
    if (["SEC", "NASDAQ", "NYSE", "AMEX"].includes(exchange)) return "United States";
    if (["HKEX", "HKG"].includes(exchange)) return "Hong Kong";
    if (["SSE", "SZSE", "CSRC"].includes(exchange)) return "China";
    const text = `${company?.headquarters || ""} ${profile?.identity?.headquarters || ""}`.toLocaleLowerCase();
    if (text.includes("hong kong") || text.includes("香港")) return "Hong Kong";
    if (text.includes("china") || text.includes("中国")) return "China";
    if (text.includes("united states") || text.includes("usa") || text.includes("美国")) return "United States";
    return "Unknown";
  }

  function coverageLabel(profile) {
    if (profile?.currentBusiness?.status === "company_reported") return "官网来源";
    if ((profile?.coverage?.evidenceCount || 0) > 0) return "部分证据";
    return "仅种子";
  }

  function coverageClass(profile) {
    if (profile?.currentBusiness?.status === "company_reported") return "supported";
    if ((profile?.coverage?.evidenceCount || 0) > 0) return "partial";
    return "seed";
  }

  function matchesCoverage(profile) {
    if (state.coverage === "All") return true;
    if (state.coverage === "company_reported") {
      return profile?.currentBusiness?.status === "company_reported";
    }
    if (state.coverage === "evidence") {
      return (
        profile?.currentBusiness?.status !== "company_reported" &&
        (profile?.coverage?.evidenceCount || 0) > 0
      );
    }
    return (profile?.coverage?.evidenceCount || 0) === 0;
  }

  function filteredCompanies() {
    const query = normalize(state.query.trim());
    return companies
      .filter((company) => {
        const profile = profileByCompanyId.get(company.id);
        const directionMatch =
          state.direction === "All" || (company.directions || []).some((item) => canonicalDirection(item) === state.direction);
        const regionMatch = state.region === "All" || companyRegion(company, profile) === state.region;
        const haystack = normalize(
          [
            company.name,
            company.ticker,
            company.headquarters,
            ...(company.aliases || []),
            ...(company.directions || []),
            ...(company.directions || []).map((item) => chineseLabel(item)),
            ...(company.modalities || []),
            ...(company.modalities || []).map((item) => chineseLabel(item)),
            profile?.currentBusiness?.summary
          ].join(" ")
        );
        return directionMatch && regionMatch && matchesCoverage(profile) && (!query || haystack.includes(query));
      })
      .sort((a, b) => {
        const aProfile = profileByCompanyId.get(a.id);
        const bProfile = profileByCompanyId.get(b.id);
        const coverageDifference =
          ["supported", "partial", "seed"].indexOf(coverageClass(aProfile)) -
          ["supported", "partial", "seed"].indexOf(coverageClass(bProfile));
        return (
          coverageDifference ||
          (bProfile?.coverage?.evidenceCount || 0) - (aProfile?.coverage?.evidenceCount || 0) ||
          a.name.localeCompare(b.name)
        );
      });
  }

  function renderMetrics() {
    const supported = (intelligence.profiles || []).filter(
      (profile) => profile.currentBusiness?.status === "company_reported"
    ).length;
    els.updatedAt.textContent = intelligence.asOfDate || data.updatedAt || "—";
    els.metricCompanies.textContent = intelligence.summary?.companyUniverseCount || companies.length;
    els.metricSupported.textContent = supported;
    els.metricAutoReviewed.textContent = intelligence.summary?.autoAcceptedCandidateCount || 0;
    els.metricCandidates.textContent = intelligence.summary?.humanReviewCandidateCount || 0;
    els.metricBusinessCovered.textContent = intelligence.profileCoverage?.companyReportedCount || supported;
    els.metricSourceFailures.textContent = intelligence.profileCoverage?.failedSourceCount || 0;
  }

  function renderDirectionOptions() {
    const directions = [...new Set(companies.flatMap((company) => (company.directions || []).map(canonicalDirection)))].sort();
    els.direction.insertAdjacentHTML(
      "beforeend",
      directions
        .map((direction) => `<option value="${escapeHtml(direction)}">${escapeHtml(chineseLabel(direction))}</option>`)
        .join("")
    );
  }

  function renderDirectory() {
    const visible = filteredCompanies();
    els.directoryCount.textContent = `${visible.length} / ${companies.length}`;
    if (!visible.length) {
      els.companyList.innerHTML = '<div class="empty-state">没有符合条件的公司。</div>';
      return;
    }
    els.companyList.innerHTML = visible
      .map((company) => {
        const profile = profileByCompanyId.get(company.id);
        const active = company.id === state.companyId ? "active" : "";
        const ticker = company.ticker || "未上市";
        return `
          <button class="company-row ${active}" data-company-id="${escapeHtml(company.id)}" type="button">
            <span class="company-row-main">
              <strong>${escapeHtml(company.name)}</strong>
              <small>${escapeHtml(chineseLabel(company.directions?.[0], "未分类"))} · ${escapeHtml(ticker)}</small>
            </span>
            <span class="coverage-dot ${coverageClass(profile)}" title="${escapeHtml(coverageLabel(profile))}"></span>
          </button>
        `;
      })
      .join("");
  }

  function renderSourceLinks(identity) {
    const sources = [
      ["官网", identity.officialUrl],
      ["管线 / 产品", identity.pipelineUrl],
      ["投资者关系", identity.irUrl]
    ];
    const links = sources
      .map(([label, value]) => [label, safeExternalUrl(value)])
      .filter(([, value]) => value)
      .map(
        ([label, value]) =>
          `<a href="${escapeHtml(value)}" target="_blank" rel="noreferrer">${escapeHtml(label)} ↗</a>`
      )
      .join("");
    const reportLinks = (identity.periodicReports || [])
      .map((report) => {
        const url = safeExternalUrl(report.url);
        return url
          ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(report.label)}（${escapeHtml(report.date || "最新")}）↗</a>`
          : "";
      })
      .filter(Boolean)
      .join("");
    const portalLinks = (identity.reportPortals || [])
      .map((portal) => {
        const url = safeExternalUrl(portal.url);
        return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(portal.label)} ↗</a>` : "";
      })
      .filter(Boolean)
      .join("");
    const status = identity.websiteStatus === "market_page_pending_official_domain"
      ? '<small class="source-status">当前链接为市场/监管来源，真实官网待解析</small>'
      : '';
    const reports = reportLinks ? `<div class="source-links report-links"><span>最新定期报告：</span>${reportLinks}</div>` : "";
    const portals = portalLinks ? `<div class="source-links report-links"><span>披露入口：</span>${portalLinks}</div>` : "";
    return links || reports || portals ? `<div class="source-links">${links}${status}</div>${reports}${portals}` : status;
  }

  function renderReportedPlans(plans) {
    if (!plans.length) {
      return `
        <div class="unknown-box">
          <strong>未知</strong>
          <p>尚未从当前来源中提取到措辞明确、可归因的未来计划。</p>
        </div>
      `;
    }
    return `<div class="item-list">${plans
      .map((plan) => {
        const url = safeExternalUrl(plan.sourceUrl);
        const text = escapeHtml(plan.text);
        const original = plan.textOriginal && plan.textOriginal !== plan.text
          ? `<details class="original-text"><summary>查看官方原文</summary><p>${escapeHtml(plan.textOriginal)}</p></details>`
          : "";
        return `
          <article>
            <span class="claim-label report">来源自述 · 未独立核验</span>
            <p>${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${text}</a>` : text}</p>
            ${original}
            <small>来源：${escapeHtml(plan.attribution || "公司官方页面")}</small>
          </article>
        `;
      })
      .join("")}</div>`;
  }

  function renderRecentEvents(events) {
    if (!events.length) return '<div class="empty-state">当前没有关联到该公司的近期记录。</div>';
    return `<div class="timeline">${events
      .slice(0, 6)
      .map((event) => {
        const url = safeExternalUrl(event.sourceUrl);
        const title = escapeHtml(event.title || "无标题记录");
        return `
          <article>
            <time>${escapeHtml(event.date || "—")}</time>
            <div>
              <strong>${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${title}</a>` : title}</strong>
              <span>${escapeHtml(chineseLabel(event.sourceType, "未知来源"))} · ${escapeHtml(chineseLabel(event.evidenceLevel, "未知"))}级证据</span>
            </div>
          </article>
        `;
      })
      .join("")}</div>`;
  }

  function renderCoverage(profile) {
    const coverage = profile.coverage || {};
    const sourceCounts = Object.entries(coverage.evidenceBySourceType || {});
    return `
      <div class="coverage-summary">
        <div><strong>${coverage.evidenceCount || 0}</strong><span>证据</span></div>
        <div><strong>${coverage.programCandidateCount || 0}</strong><span>管线项目</span></div>
        <div><strong>${escapeHtml(coverage.lastEvidenceDate || "—")}</strong><span>最近更新</span></div>
      </div>
      <div class="source-breakdown">
        ${
          sourceCounts.length
            ? sourceCounts
                .map(
                  ([source, count]) =>
                    `<span><b>${escapeHtml(count)}</b> ${escapeHtml(chineseLabel(source))}</span>`
                )
                .join("")
            : "<span>尚无来源证据</span>"
        }
      </div>
    `;
  }

  function renderCompanyDetail() {
    const company = companyById.get(state.companyId);
    const profile = profileByCompanyId.get(state.companyId);
    if (!company || !profile) {
      els.companyDetail.innerHTML = '<div class="empty-state detail-empty">请选择一家公司查看画像。</div>';
      return;
    }
    const identity = profile.identity || {};
    const classification = profile.classification || {};
    const plans = profile.futureDirection?.reportedPlans || [];
    const gaps = profile.coverage?.gaps || [];
    const summaryType = profile.currentBusiness?.summaryType || "Unknown";
    const translationPending = profile.currentBusiness?.translationStatus === "partial";
    const summaryOriginal = profile.currentBusiness?.summaryOriginal;
    const originalBusiness = summaryOriginal && summaryOriginal !== profile.currentBusiness?.summary
      ? `<details class="original-text"><summary>查看官方原文</summary><p>${escapeHtml(summaryOriginal)}</p></details>`
      : "";
    const statusClass = coverageClass(profile);
    els.companyDetail.innerHTML = `
      <div class="detail-header">
        <div>
          <p>${escapeHtml(chineseLabel(classification.companyType, "生物技术公司"))}</p>
          <h2>${escapeHtml(profile.name)}</h2>
          <span>${escapeHtml(identity.ticker || "未上市")} ${identity.exchange ? `· ${escapeHtml(identity.exchange)}` : ""} ${identity.headquarters ? `· ${escapeHtml(identity.headquarters)}` : ""}</span>
        </div>
        <span class="coverage-status ${statusClass}">${escapeHtml(coverageLabel(profile))}</span>
      </div>

      <div class="tag-list">
        ${(classification.directions || []).map((item) => `<span>${escapeHtml(chineseLabel(item))}</span>`).join("")}
        ${(classification.modalities || []).map((item) => `<span>${escapeHtml(chineseLabel(item))}</span>`).join("")}
      </div>
      ${renderSourceLinks(identity)}
      ${identity.legalNameStatus === "unresolved" ? '<p class="identity-note">法定公司全称尚未从上市文件或官网核验。</p>' : ""}

      <section class="detail-section business-section">
        <div class="detail-section-heading">
          <div><span>01</span><h3>当前主营业务</h3></div>
          <span class="claim-label ${summaryType === "Report" ? "report" : "unknown"}">${escapeHtml(chineseLabel(summaryType))}${translationPending ? " · 待翻译" : ""}</span>
        </div>
        <p class="business-summary">${escapeHtml(profile.currentBusiness?.summary || "当前没有足够证据形成业务摘要。")}</p>
        ${originalBusiness}
      </section>

      <section class="detail-section">
        <div class="detail-section-heading">
          <div><span>02</span><h3>未来发展动向</h3></div>
        </div>
        ${renderReportedPlans(plans)}
      </section>

      <section class="detail-section">
        <div class="detail-section-heading">
          <div><span>03</span><h3>近期观察</h3></div>
        </div>
        ${renderRecentEvents(profile.recentEvents || [])}
      </section>

      <section class="detail-section coverage-section">
        <div class="detail-section-heading">
          <div><span>04</span><h3>证据覆盖</h3></div>
        </div>
        ${renderCoverage(profile)}
      </section>

      <section class="detail-section unknown-section">
        <div class="detail-section-heading">
          <div><span>05</span><h3>当前未知与缺口</h3></div>
        </div>
        ${
          gaps.length
            ? `<ul>${gaps.map((gap) => `<li>${escapeHtml(gap)}</li>`).join("")}</ul>`
            : "<p>当前未记录额外覆盖缺口。</p>"
        }
      </section>
    `;
  }

  function selectCompany(companyId, updateHash = true) {
    if (!companyById.has(companyId)) return;
    state.companyId = companyId;
    if (updateHash) window.history.replaceState(null, "", `#${encodeURIComponent(companyId)}`);
    renderDirectory();
    renderCompanyDetail();
    if (window.innerWidth < 860) {
      els.companyDetail.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function renderCandidates() {
    const candidates = intelligence.candidates || [];
    const humanQueue = candidates.filter(
      (candidate) => candidate.intakeReview?.humanReviewRequired !== false
    );
    const acceptedCount = candidates.filter(
      (candidate) => candidate.intakeReview?.decision === "accepted"
    ).length;
    els.candidateCount.textContent = humanQueue.length;
    els.candidateSummary.textContent = `本轮自动审核通过 ${acceptedCount} 家，${humanQueue.length} 家需要人工处理。自动通过表示实体身份和生物技术相关性满足公司池准入条件，不代表官网业务画像已经完整。`;
    if (!humanQueue.length) {
      els.candidateList.innerHTML = '<div class="empty-state">当前没有需要人工处理的候选公司。</div>';
      return;
    }
    const visible = humanQueue.slice(0, 20);
    els.candidateList.innerHTML = visible
      .map((candidate) => {
        const source = candidate.sources?.[0] || {};
        const url = safeExternalUrl(source.sourceUrl);
        const themes = candidate.classificationHints?.directions || candidate.classificationHints?.themes || [];
        const review = candidate.intakeReview || {};
        const status = review.decision === "needs_human" ? "需要人工处理" : "审核状态未知";
        const sourceTypes = candidate.sourceTypes || [source.sourceType].filter(Boolean);
        const reviewActions = state.reviewApiEnabled
          ? `
              <div class="review-actions" aria-label="人工审核操作">
                <button type="button" data-candidate-id="${escapeHtml(candidate.id)}" data-review-decision="accepted">接受</button>
                <button type="button" data-candidate-id="${escapeHtml(candidate.id)}" data-review-decision="merged">合并</button>
                <button class="danger" type="button" data-candidate-id="${escapeHtml(candidate.id)}" data-review-decision="rejected">排除</button>
              </div>
            `
          : '<small class="review-readonly">当前为只读预览；使用本地审核服务可直接处理。</small>';
        return `
          <article class="candidate-card">
            <div>
              <span class="claim-label ${review.humanReviewRequired ? "unknown" : "report"}">${escapeHtml(status)}</span>
              <h3>${escapeHtml(candidate.name)}</h3>
              <p>${escapeHtml(review.reviewReasons?.[0] || candidate.discoveryReasons?.[0] || "来源中发现了新的公司型实体。")}</p>
              <div class="tag-list">
                ${sourceTypes.map((item) => `<span>${escapeHtml(chineseLabel(item))}</span>`).join("")}
                ${themes.slice(0, 4).map((theme) => `<span>${escapeHtml(chineseLabel(theme))}</span>`).join("")}
              </div>
            </div>
            <div class="candidate-meta">
              <strong>${escapeHtml(review.reviewScore ?? candidate.discoveryScore)}</strong>
              <span>自动审核分</span>
              <span>${escapeHtml(candidate.mentionCount || 1)} 条提及 · ${escapeHtml(candidate.sourceCount || 1)} 类来源</span>
              ${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">核对来源 ↗</a>` : ""}
              ${reviewActions}
            </div>
          </article>
        `;
      })
      .join("") +
      (humanQueue.length > visible.length
        ? `<div class="candidate-overflow">当前显示 ${visible.length} 家；其余 ${humanQueue.length - visible.length} 家保留在人工异常队列中。</div>`
        : "");
  }

  async function detectReviewApi() {
    try {
      const response = await fetch("./api/review-capabilities", { cache: "no-store" });
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) return;
      const payload = await response.json();
      state.reviewApiEnabled = payload.enabled === true;
      state.reviewer = payload.reviewer || "";
      renderCandidates();
    } catch (_error) {
      state.reviewApiEnabled = false;
    }
  }

  async function submitCandidateReview(button) {
    const candidateId = button.dataset.candidateId;
    const decision = button.dataset.reviewDecision;
    const candidate = (intelligence.candidates || []).find((item) => item.id === candidateId);
    if (!candidate) return;
    let targetCompanyId = null;
    if (decision === "merged") {
      targetCompanyId = window.prompt("请输入要合并到的正式 companyId：", "");
      if (!targetCompanyId) return;
    }
    const defaults = {
      accepted: "已核对官方来源，确认该实体属于生物技术公司并纳入公司池。",
      rejected: "已核对来源，确认该实体不应纳入公司池。",
      merged: `已核对来源，确认该候选与 ${targetCompanyId || "已有公司"} 为同一实体。`
    };
    const reason = window.prompt("请记录审核依据：", defaults[decision] || "人工审核结论。");
    if (!reason) return;
    const buttons = [...els.candidateList.querySelectorAll("button[data-review-decision]")];
    buttons.forEach((item) => { item.disabled = true; });
    button.textContent = "处理中…";
    try {
      const response = await fetch("./api/candidate-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidateId,
          decision,
          reason,
          targetCompanyId,
          evidenceUrls: (candidate.sources || []).map((item) => item.sourceUrl).filter(Boolean)
        })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "审核写入失败");
      const refreshedUrl = new URL(window.location.href);
      refreshedUrl.searchParams.set("reviewed", Date.now().toString());
      window.location.replace(refreshedUrl.toString());
    } catch (error) {
      window.alert(`审核失败：${error.message}`);
      renderCandidates();
    }
  }

  function bindEvents() {
    els.search.addEventListener("input", (event) => {
      state.query = event.target.value;
      renderDirectory();
    });
    els.direction.addEventListener("change", (event) => {
      state.direction = event.target.value;
      renderDirectory();
    });
    els.coverage.addEventListener("change", (event) => {
      state.coverage = event.target.value;
      renderDirectory();
    });
    els.region.addEventListener("change", (event) => {
      state.region = event.target.value;
      renderDirectory();
    });
    els.companyList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-company-id]");
      if (button) selectCompany(button.dataset.companyId);
    });
    els.candidateList.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-review-decision]");
      if (button) submitCandidateReview(button);
    });
    window.addEventListener("hashchange", () => {
      const companyId = decodeURIComponent(window.location.hash.slice(1));
      if (companyById.has(companyId)) selectCompany(companyId, false);
    });
  }

  renderMetrics();
  renderDirectionOptions();
  renderDirectory();
  renderCompanyDetail();
  renderCandidates();
  bindEvents();
  detectReviewApi();
})();
