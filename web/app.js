(() => {
  "use strict";

  const data = window.NFL_DRAFT_DATA;
  const storageKey = "nfl-fantasy-draft-board-v1";
  const state = { position: "ALL", query: "", sort: "draft", picks: [], expanded: null };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);

  const positionClass = (position) => `position position-${position.toLowerCase()}`;
  const teamLogo = (team) => {
    const aliases = { JAX: "jax", LA: "lar", WAS: "wsh" };
    return `https://a.espncdn.com/i/teamlogos/nfl/500/${aliases[team] || team.toLowerCase()}.png`;
  };

  function loadPicks() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey));
      if (Array.isArray(saved)) state.picks = saved.filter((pick) => pick.id && pick.owner);
    } catch (_error) {
      state.picks = [];
    }
  }

  function savePicks() {
    localStorage.setItem(storageKey, JSON.stringify(state.picks));
  }

  function statusFor(id) {
    return [...state.picks].reverse().find((pick) => pick.id === id)?.owner || "available";
  }

  function setPlayerStatus(id, owner) {
    state.picks = state.picks.filter((pick) => pick.id !== id);
    if (owner !== "available") state.picks.push({ id, owner, changedAt: Date.now() });
    savePicks();
    render();
  }

  function filteredPlayers() {
    const query = state.query.trim().toLowerCase();
    const players = data.players.filter((player) => {
      const positionMatch = state.position === "ALL" || player.position === state.position;
      const textMatch = !query || `${player.name} ${player.team} ${player.position}`.toLowerCase().includes(query);
      return positionMatch && textMatch;
    });
    const sorters = {
      draft: (a, b) => a.draftRank - b.draftRank,
      points: (a, b) => b.projectedPoints - a.projectedPoints || a.rank - b.rank,
      weekly: (a, b) => b.pointsPerGame - a.pointsPerGame || a.rank - b.rank,
      position: (a, b) => a.position.localeCompare(b.position) || a.positionRank - b.positionRank,
      lift: (a, b) => b.modelLift - a.modelLift || a.rank - b.rank,
      name: (a, b) => a.name.localeCompare(b.name),
    };
    return players.sort(sorters[state.sort]);
  }

  function statItems(player) {
    const stats = player.stats;
    const byPosition = {
      QB: [["Pass yd", "passing_yards"], ["Pass TD", "passing_tds"], ["INT", "passing_interceptions"], ["Rush yd", "rushing_yards"], ["Rush TD", "rushing_tds"]],
      RB: [["Rush yd", "rushing_yards"], ["Rush TD", "rushing_tds"], ["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"], ["Fumbles", "fumbles_lost_total"]],
      WR: [["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"], ["Rush yd", "rushing_yards"], ["Rush TD", "rushing_tds"], ["Fumbles", "fumbles_lost_total"]],
      TE: [["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"], ["Fumbles", "fumbles_lost_total"]],
      K: [["PAT", "pat_made"], ["FG 0-19", "fg_made_0_19"], ["FG 20-29", "fg_made_20_29"], ["FG 30-39", "fg_made_30_39"], ["FG 40-49", "fg_made_40_49"], ["FG 50+", "fg_made_50_59"]],
    };
    return (byPosition[player.position] || byPosition.WR).map(([label, key]) => `
      <div><span>${label}</span><strong>${Number(stats[key] || 0).toFixed(1)}</strong></div>
    `).join("");
  }

  function gameColumns(position) {
    const columns = {
      QB: [["Pass yd", "passing_yards"], ["Pass TD", "passing_tds"], ["INT", "passing_interceptions"], ["Rush yd", "rushing_yards"]],
      RB: [["Rush yd", "rushing_yards"], ["Rush TD", "rushing_tds"], ["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"]],
      WR: [["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"], ["Rush yd", "rushing_yards"]],
      TE: [["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"]],
      K: [["FGM", "field_goals_made"], ["PAT", "pat_made"]],
    };
    return columns[position] || columns.WR;
  }

  function gameStat(game, key) {
    if (key === "field_goals_made") {
      return ["fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_"]
        .reduce((total, field) => total + Number(game.stats[field] || 0), 0);
    }
    return Number(game.stats[key] || 0);
  }

  function weeklyProjectionTable(player) {
    const columns = gameColumns(player.position);
    const headers = columns.map(([label]) => `<th class="number-cell">${label}</th>`).join("");
    const rows = player.games.map((game) => `
      <tr>
        <td><strong>${game.week}</strong></td>
        <td><span class="matchup-venue">${game.venue}</span> ${escapeHtml(game.opponent)}</td>
        <td class="number-cell weekly-projection">${game.projectedPoints.toFixed(2)}</td>
        ${columns.map(([, key]) => `<td class="number-cell">${gameStat(game, key).toFixed(1)}</td>`).join("")}
      </tr>
    `).join("");
    return `
      <div class="weekly-wrap">
        <div class="detail-heading">
          <div><strong>Game-by-game projections</strong><span>${data.projectionSeason} out-of-sample validation</span></div>
          <small>Opponent-aware pregame model output</small>
        </div>
        <div class="weekly-scroll">
          <table class="weekly-table">
            <thead><tr><th>Week</th><th>Matchup</th><th class="number-cell">Projected</th>${headers}</tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  function playerDetail(player) {
    return `
      <div class="player-detail">
        <div class="season-components">
          <span class="detail-label">Projected season components</span>
          <div class="stat-grid">${statItems(player)}</div>
        </div>
        ${weeklyProjectionTable(player)}
      </div>
    `;
  }

  function statusMarkup(player, status) {
    if (status === "mine") return '<span class="status-pill mine">My roster</span>';
    if (status === "other") return '<span class="status-pill taken">Taken</span>';
    return '<span class="status-pill available">Available</span>';
  }

  function playerRow(player) {
    const status = statusFor(player.id);
    const expanded = state.expanded === player.id;
    const rowClass = status === "available" ? "" : ` ${status}`;
    const displayedRank = state.sort === "draft" ? player.draftRank : player.rank;
    return `
      <tr class="player-row${rowClass}" data-id="${escapeHtml(player.id)}">
        <td class="rank-cell"><strong>${displayedRank}</strong><small>${player.position}${player.positionRank}</small></td>
        <td>
          <div class="player-cell">
            <img src="${teamLogo(player.team)}" alt="" onerror="this.hidden=true">
            <span><strong>${escapeHtml(player.name)}</strong><small>${player.projectedGames} projected games</small></span>
          </div>
        </td>
        <td><span class="${positionClass(player.position)}">${escapeHtml(player.position)}</span></td>
        <td class="team-cell">${escapeHtml(player.team)}</td>
        <td class="number-cell projection"><strong>${player.projectedPoints.toFixed(1)}</strong></td>
        <td class="number-cell">${player.pointsPerGame.toFixed(2)}</td>
        <td class="number-cell draft-value">${player.draftValue > 0 ? "+" : ""}${player.draftValue.toFixed(1)}</td>
        <td>${statusMarkup(player, status)}</td>
        <td class="actions-cell">
          <div class="row-actions">
            <button type="button" data-action="mine" data-id="${escapeHtml(player.id)}" title="Add to my roster" aria-label="Add ${escapeHtml(player.name)} to my roster"><i data-lucide="user-plus"></i></button>
            <button type="button" data-action="other" data-id="${escapeHtml(player.id)}" title="Mark drafted by someone else" aria-label="Mark ${escapeHtml(player.name)} drafted by someone else"><i data-lucide="user-x"></i></button>
            <button type="button" data-action="expand" data-id="${escapeHtml(player.id)}" title="View game-by-game projections" aria-label="View ${escapeHtml(player.name)} game-by-game projections" aria-expanded="${expanded}"><i data-lucide="${expanded ? "chevron-up" : "chevron-down"}"></i></button>
          </div>
        </td>
      </tr>
      ${expanded ? `
        <tr class="detail-row">
          <td colspan="9">${playerDetail(player)}</td>
        </tr>
      ` : ""}
    `;
  }

  function renderSummary(players) {
    const available = players.filter((player) => statusFor(player.id) === "available");
    const best = available[0];
    $("bestName").textContent = best?.name || "No player available";
    $("bestMeta").textContent = best ? `${best.position}${best.positionRank} · ${best.team}` : "-";
    $("bestPoints").textContent = best ? best.projectedPoints.toFixed(1) : "-";
    $("availableCount").textContent = data.players.filter((player) => statusFor(player.id) === "available").length;
    $("mineCount").textContent = data.players.filter((player) => statusFor(player.id) === "mine").length;
    $("takenCount").textContent = data.players.filter((player) => statusFor(player.id) === "other").length;
    $("undoButton").disabled = state.picks.length === 0;
  }

  function render() {
    const players = filteredPlayers();
    $("rankingsBody").innerHTML = players.map(playerRow).join("");
    $("emptyState").hidden = players.length > 0;
    renderSummary(players);
    if (window.lucide) window.lucide.createIcons();
  }

  function bindEvents() {
    $("positionFilters").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-position]");
      if (!button) return;
      state.position = button.dataset.position;
      document.querySelectorAll("[data-position]").forEach((item) => item.classList.toggle("active", item === button));
      render();
    });
    $("searchInput").addEventListener("input", (event) => {
      state.query = event.target.value;
      render();
    });
    $("sortSelect").addEventListener("change", (event) => {
      state.sort = event.target.value;
      render();
    });
    $("rankingsBody").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) {
        const row = event.target.closest("tr.player-row[data-id]");
        if (!row) return;
        state.expanded = state.expanded === row.dataset.id ? null : row.dataset.id;
        render();
        return;
      }
      const { action, id } = button.dataset;
      if (action === "expand") {
        state.expanded = state.expanded === id ? null : id;
        render();
        return;
      }
      setPlayerStatus(id, statusFor(id) === action ? "available" : action);
    });
    $("undoButton").addEventListener("click", () => {
      state.picks.pop();
      savePicks();
      render();
    });
    $("resetButton").addEventListener("click", () => {
      if (!state.picks.length || window.confirm("Reset every draft-board selection?")) {
        state.picks = [];
        savePicks();
        render();
      }
    });
  }

  function boot() {
    if (!data?.players?.length) {
      $("error").textContent = "Projection data is missing. Run: nfl-fantasy draft-board";
      $("error").hidden = false;
      return;
    }
    loadPicks();
    $("seasonLabel").textContent = `${data.projectionSeason} validation season`;
    $("modelStatus").textContent = `${data.scoring} · development model`;
    $("methodLabel").textContent = `${data.scope}. Season sum of game-level forecasts; not a live ${new Date().getFullYear()} preseason ranking.`;
    $("methodLabel").textContent += ` Draft order: ${data.draftFormat}.`;
    $("footerScope").textContent = `${data.projectionSeason} · ${data.scoring} · ${data.players.length} fantasy-relevant players`;
    const generated = new Date(data.generatedAt);
    $("updatedLabel").textContent = `Generated ${generated.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
    bindEvents();
    render();
    $("app").hidden = false;
  }

  window.addEventListener("DOMContentLoaded", boot);
})();
