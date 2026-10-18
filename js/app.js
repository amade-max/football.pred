(() => {
  "use strict";

  const STALE_DAYS = 7;          // aviso se o último resultado for mais velho
  const LIVE_WINDOW_H = 3;       // até 3h após o início: "em andamento"

  let data = null;
  let currentLeague = null;
  let currentView = "upcoming";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  async function loadData() {
    try {
      const res = await fetch("data/matches.json?t=" + Date.now());
      if (!res.ok) throw new Error("Falha ao carregar dados");
      data = await res.json();
      init();
    } catch (err) {
      $("#content").innerHTML = `
        <div class="empty">
          <p>Não foi possível carregar os dados.</p>
          <p class="hint">
            Rode o script <code>scripts/update_data.py</code> ou aguarde o GitHub Action.
          </p>
        </div>`;
      console.error(err);
    }
  }

  function init() {
    const gen = data.generated_at
      ? new Date(data.generated_at).toLocaleString("pt-BR", {
          day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
        })
      : "—";
    $("#last-update").textContent = `Atualizado: ${gen}`;

    const tabs = $("#league-tabs");
    tabs.innerHTML = "";
    data.leagues.forEach((lg, i) => {
      const btn = document.createElement("button");
      btn.className = "tab" + (i === 0 ? " active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", i === 0 ? "true" : "false");
      btn.textContent = `${lg.flag} ${lg.name}`;
      btn.dataset.code = lg.code;
      btn.addEventListener("click", () => selectLeague(lg.code));
      tabs.appendChild(btn);
    });

    currentLeague = data.leagues[0]?.code;
    render();

    $$('input[name="view"]').forEach((radio) => {
      radio.addEventListener("change", (e) => {
        currentView = e.target.value;
        render();
      });
    });

    // Reavalia jogos "em andamento" sem recarregar a página
    setInterval(() => { if (data) render(); }, 60 * 1000);
  }

  function selectLeague(code) {
    currentLeague = code;
    $$(".tab").forEach((t) => {
      const on = t.dataset.code === code;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    render();
  }

  // ---------- Avisos sobre a qualidade dos dados ----------

  function notices(league) {
    const out = [];
    if (data.provisional) {
      out.push(
        `<strong>Dados provisórios.</strong> As previsões usam só uma amostra pequena de resultados. ` +
        `Execute o workflow <em>Update Football Data</em> para carregar a época completa.`
      );
    }
    if (league.stale_fetch) {
      out.push(`Não foi possível atualizar esta liga na última execução; a mostrar os dados anteriores.`);
    }
    if (league.latest_result) {
      const days = Math.floor((Date.now() - new Date(league.latest_result + "T12:00:00Z")) / 864e5);
      if (days > STALE_DAYS) {
        out.push(
          `O último resultado na fonte é de <strong>${formatDate(league.latest_result)}</strong> ` +
          `(há ${days} dias). A forma e as previsões podem estar desatualizadas.`
        );
      }
    }
    if (league.pending_past > 0) {
      out.push(
        `${league.pending_past} jogo(s) já realizado(s) ainda sem resultado na fonte; ` +
        `não entram no modelo até serem publicados.`
      );
    }
    return out.map((t) => `<div class="notice">${t}</div>`).join("");
  }

  // ---------- Cartões ----------

  function formPills(formStr) {
    if (!formStr || formStr === "—") return "—";
    return formStr
      .split("")
      .map((c) => `<span class="pill ${esc(c)}" title="${{ W: "Vitória", D: "Empate", L: "Derrota" }[c] || ""}">${esc(c)}</span>`)
      .join("");
  }

  const CONF_HELP =
    "Combina a diferença entre as duas opções mais prováveis com a quantidade de jogos " +
    "recentes disponíveis das duas equipas. Mesmo 'alta' está longe de ser certeza.";

  function mostLikelyBadge(m, status) {
    if (!m.best_bet) return "";
    const level = status === "live" ? "baixa" : m.conf_level || "baixa";
    return `
      <div class="best-bet ${esc(level)}">
        <span class="best-icon">★</span>
        <span class="best-text">
          Resultado mais provável: <strong>${esc(m.best_bet_label)}</strong>
          <span class="best-prob">${m.best_bet_prob}%</span>
        </span>
        <span class="conf-tag ${esc(level)}" title="${esc(CONF_HELP)}">confiança ${esc(m.conf_level)}</span>
      </div>`;
  }

  /** "upcoming" | "live" | "past" a partir da hora de início (UTC). */
  function matchStatus(m) {
    if (!m.kickoff_utc) return "upcoming";
    const diffH = (Date.now() - new Date(m.kickoff_utc).getTime()) / 36e5;
    if (diffH < 0) return "upcoming";
    return diffH <= LIVE_WINDOW_H ? "live" : "past";
  }

  function statusTag(m, status) {
    if (status === "live") return `<span class="status live">Em andamento</span>`;
    const today = new Date().toISOString().slice(0, 10);
    if (m.date === today) return `<span class="status today">Hoje</span>`;
    return "";
  }

  function renderUpcoming(league) {
    const all = league.upcoming.map((m) => ({ m, status: matchStatus(m) }));
    // jogos que já terminaram (resultado ainda não publicado) saem da lista
    const items = all.filter((x) => x.status !== "past");
    const hidden = all.length - items.length;

    if (!items.length) {
      return `<div class="empty">Nenhum jogo futuro encontrado nesta liga.</div>`;
    }

    return `
      ${hidden ? `<p class="hint-line">${hidden} jogo(s) de hoje já terminaram e aguardam o resultado na fonte.</p>` : ""}
      <div class="match-list">
        ${items
          .map(({ m, status }) => `
          <article class="match-card ${m.best_bet && status === "upcoming" ? "has-best" : ""}">
            <div class="match-header">
              <span>${esc(m.round)}</span>
              <span>${statusTag(m, status)} ${formatDate(m.date)}${m.time ? " · " + esc(m.time) : ""}</span>
            </div>
            <div class="match-teams">
              <div class="team home">${esc(shortName(m.home))}</div>
              <div class="vs">vs</div>
              <div class="team away">${esc(shortName(m.away))}</div>
            </div>
            ${mostLikelyBadge(m, status)}
            <div class="probs">
              ${probBox("Casa", "home", m.prob_home, m.best_bet === "H")}
              ${probBox("Empate", "draw", m.prob_draw, m.best_bet === "D")}
              ${probBox("Fora", "away", m.prob_away, m.best_bet === "A")}
            </div>
            <div class="extras">
              <span title="Golos esperados pelo modelo">xG ${m.lambda_home} – ${m.lambda_away}</span>
              <span title="Placar individual mais provável">Placar provável ${esc(m.top_score)}</span>
              <span>+2,5 gols ${m.over25}%</span>
              <span>Ambos marcam ${m.btts}%</span>
            </div>
            <div class="form-row">
              <span>Forma: <span class="form-pills">${formPills(m.form_home)}</span></span>
              <span>Forma: <span class="form-pills">${formPills(m.form_away)}</span></span>
            </div>
          </article>`)
          .join("")}
      </div>`;
  }

  function probBox(label, cls, value, isBest) {
    return `
      <div class="prob ${cls} ${isBest ? "is-best" : ""}">
        <div class="label">${label}</div>
        <div class="value">${value}%</div>
        <div class="bar ${cls}"><span style="width:${Math.min(100, value)}%"></span></div>
      </div>`;
  }

  function renderRecent(league) {
    const matches = league.recent;
    if (!matches.length) {
      return `<div class="empty">Nenhum resultado recente.</div>`;
    }
    const label = { H: "Vitória Casa", A: "Vitória Fora", D: "Empate" };
    return `
      <div class="match-list">
        ${matches
          .map((m) => `
          <article class="match-card">
            <div class="match-header">
              <span>${esc(m.round)}</span>
              <span>${formatDate(m.date)}</span>
            </div>
            <div class="match-teams">
              <div class="team home">${esc(shortName(m.home))}</div>
              <div class="score">${esc(m.score || "—")}</div>
              <div class="team away">${esc(shortName(m.away))}</div>
            </div>
            <div class="center">
              <span class="result-badge ${esc(m.result)}">${label[m.result] || ""}</span>
            </div>
          </article>`)
          .join("")}
      </div>`;
  }

  function render() {
    const league = data.leagues.find((l) => l.code === currentLeague);
    if (!league) {
      $("#content").innerHTML = `<div class="empty">Liga não encontrada.</div>`;
      return;
    }
    $("#content").innerHTML =
      notices(league) +
      (currentView === "upcoming" ? renderUpcoming(league) : renderRecent(league));
  }

  function formatDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
  }

  function shortName(name) {
    return (name || "")
      .replace(/ FC$/i, "")
      .replace(/ AFC$/i, "")
      .replace(/ & Hove Albion/i, "")
      .replace(/ Hotspur/i, "")
      .trim();
  }

  loadData();
})();
