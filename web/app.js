(() => {
  "use strict";

  const data = window.NFL_DRAFT_DATA;
  const storageKey = "nfl-fantasy-draft-board-v3";
  const legacyStorageKey = "nfl-fantasy-draft-board-v1";
  const defaultConfig = data?.draftConfig || {
    teams: 12, draftSlot: 1, rosterSlots: { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1 },
  };
  const state = {
    position: "ALL", query: "", sort: "draft", picks: [], expanded: null,
    teams: Number(defaultConfig.teams || 12), draftSlot: Number(defaultConfig.draftSlot || 1), scenario: "adaptive", policy: "roster",
  };
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
      if (saved && Array.isArray(saved.picks)) {
        state.picks = saved.picks.filter((pick) => pick.id && pick.owner);
        state.teams = Number(saved.teams || state.teams);
        state.draftSlot = Math.min(state.teams, Number(saved.draftSlot || state.draftSlot));
        state.scenario = saved.scenario || state.scenario;
        state.policy = saved.policy || state.policy;
        return;
      }
      const legacy = JSON.parse(localStorage.getItem(legacyStorageKey));
      if (Array.isArray(legacy)) state.picks = legacy.filter((pick) => pick.id && pick.owner);
    } catch (_error) {
      state.picks = [];
    }
  }

  function savePicks() {
    localStorage.setItem(storageKey, JSON.stringify({
      picks: state.picks, teams: state.teams, draftSlot: state.draftSlot, scenario: state.scenario, policy: state.policy,
    }));
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

  function snakeTeam(overallPick) {
    const round = Math.floor((overallPick - 1) / state.teams) + 1;
    const inRound = ((overallPick - 1) % state.teams) + 1;
    return round % 2 ? inRound : state.teams - inRound + 1;
  }

  function nextPickForTeam(afterPick) {
    let pick = afterPick + 1;
    while (snakeTeam(pick) !== state.draftSlot) pick += 1;
    return pick;
  }

  function starterCounts(pointsKey = "projectedPoints") {
    const slots = defaultConfig.rosterSlots;
    const counts = { QB: state.teams * slots.QB, RB: state.teams * slots.RB, WR: state.teams * slots.WR, TE: state.teams * slots.TE, K: state.teams * slots.K };
    const flexPool = ["RB", "WR", "TE"].flatMap((position) => data.players
      .filter((player) => player.position === position)
      .sort((a, b) => b[pointsKey] - a[pointsKey])
      .slice(counts[position])
      .map((player) => ({ player, points: player[pointsKey] })));
    flexPool.sort((a, b) => b.points - a.points);
    flexPool.slice(0, state.teams * slots.FLEX).forEach(({ player }) => { counts[player.position] += 1; });
    return counts;
  }

  function formatMetrics(pointsKey = "projectedPoints") {
    const counts = starterCounts(pointsKey);
    const replacements = {};
    Object.keys(counts).forEach((position) => {
      const ordered = data.players.filter((player) => player.position === position).sort((a, b) => b[pointsKey] - a[pointsKey]);
      replacements[position] = ordered[Math.min(Math.max(counts[position], 1), ordered.length) - 1]?.[pointsKey] || 0;
    });
    const ordered = data.players.map((player) => ({
      player, value: player[pointsKey] - replacements[player.position], replacement: replacements[player.position],
    })).sort((a, b) => b.value - a.value || b.player[pointsKey] - a.player[pointsKey] || a.player.name.localeCompare(b.player.name));
    const metrics = new Map();
    ordered.forEach((item, index) => metrics.set(item.player.id, { value: item.value, replacement: item.replacement, rank: index + 1 }));
    return metrics;
  }

  function optimalLineupValue(players) {
    const slots = defaultConfig.rosterSlots;
    const selected = new Set();
    let total = 0;
    ["QB", "RB", "WR", "TE", "K"].forEach((position) => {
      players.filter((player) => player.position === position)
        .sort((a, b) => b.projectedPoints - a.projectedPoints)
        .slice(0, slots[position])
        .forEach((player) => { selected.add(player.id); total += player.projectedPoints; });
    });
    players.filter((player) => ["RB", "WR", "TE"].includes(player.position) && !selected.has(player.id))
      .sort((a, b) => b.projectedPoints - a.projectedPoints)
      .slice(0, slots.FLEX)
      .forEach((player) => { total += player.projectedPoints; });
    return total;
  }

  function rosterValue(players, metrics) {
    const slots = defaultConfig.rosterSlots;
    const replacements = {};
    data.players.forEach((player) => { replacements[player.position] = metrics.get(player.id).replacement; });
    const replacementPlayers = ["QB", "RB", "WR", "TE", "K"].flatMap((position) =>
      Array.from({ length: slots[position] + (["RB", "WR", "TE"].includes(position) ? slots.FLEX : 0) }, (_, index) => ({
        id: `replacement-${position}-${index}`,
        position,
        projectedPoints: replacements[position] || 0,
      })));
    return optimalLineupValue([...players, ...replacementPlayers]);
  }

  function runPosition() {
    if (state.scenario === "rb_rush") return "RB";
    if (state.scenario === "wr_rush") return "WR";
    if (state.scenario !== "adaptive") return null;
    const otherPicks = state.picks.filter((pick) => pick.owner === "other");
    const recent = otherPicks.slice(-Math.min(8, otherPicks.length))
      .map((pick) => data.players.find((player) => player.id === pick.id)?.position)
      .filter(Boolean);
    if (recent.length < 4) return null;
    const counts = recent.reduce((result, position) => ({ ...result, [position]: (result[position] || 0) + 1 }), {});
    const leader = ["RB", "WR"].sort((a, b) => (counts[b] || 0) - (counts[a] || 0))[0];
    return (counts[leader] || 0) >= Math.ceil(recent.length / 2) ? leader : null;
  }

  function opponentRemovals(available, candidateId, count, afterPick, metrics) {
    const pool = available.filter((player) => player.id !== candidateId);
    const removed = [];
    const forcedPosition = runPosition();
    for (let index = 0; index < count && pool.length; index += 1) {
      const overallPick = afterPick + index + 1;
      const forceRun = forcedPosition && overallPick <= state.teams * 2;
      const eligible = forceRun ? pool.filter((player) => player.position === forcedPosition) : pool;
      const source = eligible.length ? eligible : pool;
      source.sort((a, b) => metrics.get(a.id).rank - metrics.get(b.id).rank);
      const chosen = source[0];
      removed.push(chosen);
      pool.splice(pool.findIndex((player) => player.id === chosen.id), 1);
    }
    return { survivors: pool, removed };
  }

  function recommendationState() {
    const available = data.players.filter((player) => statusFor(player.id) === "available");
    const myRoster = data.players.filter((player) => statusFor(player.id) === "mine");
    const metrics = formatMetrics();
    const currentPick = state.picks.length + 1;
    const onClock = snakeTeam(currentPick) === state.draftSlot;
    const decisionPick = onClock ? currentPick : nextPickForTeam(currentPick - 1);
    const nextTurn = nextPickForTeam(decisionPick);
    const opponentPicks = nextTurn - decisionPick - 1;
    const baselineRemoved = new Set(opponentRemovals(available, "", opponentPicks, decisionPick, metrics).removed.map((player) => player.id));
    const candidates = available.map((candidate) => {
      const simulation = opponentRemovals(available, candidate.id, opponentPicks, decisionPick, metrics);
      const nextAtPosition = simulation.survivors
        .filter((player) => player.position === candidate.position)
        .sort((a, b) => b.projectedPoints - a.projectedPoints)[0];
      const likelyGone = baselineRemoved.has(candidate.id);
      const nextOptions = ["QB", "RB", "WR", "TE", "K"].map((position) =>
        simulation.survivors
          .filter((player) => player.position === position)
          .sort((a, b) => b.projectedPoints - a.projectedPoints)[0])
        .filter(Boolean);
      const lineupCeiling = nextOptions.length
        ? Math.max(...nextOptions.map((nextPlayer) => rosterValue([...myRoster, candidate, nextPlayer], metrics)))
        : rosterValue([...myRoster, candidate], metrics);
      const withoutCandidate = rosterValue(myRoster, metrics);
      const immediateValue = rosterValue([...myRoster, candidate], metrics);
      return {
        player: candidate,
        lineupCeiling,
        immediateValue,
        protectedGain: lineupCeiling - withoutCandidate,
        nextTurnGap: candidate.projectedPoints - Number(nextAtPosition?.projectedPoints || 0),
        likelyGone,
        baseValue: metrics.get(candidate.id).value,
      };
    });
    candidates.sort((a, b) => {
      if (state.policy === "lookahead") {
        return b.lineupCeiling - a.lineupCeiling
          || Number(b.likelyGone) - Number(a.likelyGone)
          || b.nextTurnGap - a.nextTurnGap
          || b.baseValue - a.baseValue
          || b.player.projectedPoints - a.player.projectedPoints;
      }
      return b.immediateValue - a.immediateValue
        || b.baseValue - a.baseValue
        || Number(b.likelyGone) - Number(a.likelyGone)
        || b.nextTurnGap - a.nextTurnGap
        || b.player.projectedPoints - a.player.projectedPoints;
    });
    candidates.forEach((candidate, index) => { candidate.rank = index + 1; });
    return { candidates, byId: new Map(candidates.map((candidate) => [candidate.player.id, candidate])), currentPick, decisionPick, nextTurn, opponentPicks, onClock, metrics };
  }

  function filteredPlayers(recommendations, actualMetrics) {
    const query = state.query.trim().toLowerCase();
    const players = data.players.filter((player) => {
      const positionMatch = state.position === "ALL" || player.position === state.position;
      const textMatch = !query || `${player.name} ${player.team} ${player.position}`.toLowerCase().includes(query);
      return positionMatch && textMatch;
    });
    const sorters = {
      draft: (a, b) => (recommendations.byId.get(a.id)?.rank || 9999) - (recommendations.byId.get(b.id)?.rank || 9999) || recommendations.metrics.get(a.id).rank - recommendations.metrics.get(b.id).rank,
      actual_draft: (a, b) => actualMetrics.get(a.id).rank - actualMetrics.get(b.id).rank,
      points: (a, b) => b.projectedPoints - a.projectedPoints || a.rank - b.rank,
      weekly: (a, b) => b.pointsPerGame - a.pointsPerGame || a.rank - b.rank,
      actual: (a, b) => a.actualRank - b.actualRank,
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
        <td class="number-cell actual-result actual-column">${data.hasActuals ? game.actualPoints.toFixed(2) : "-"}</td>
        ${columns.map(([, key]) => `<td class="number-cell">${gameStat(game, key).toFixed(1)}</td>`).join("")}
      </tr>
    `).join("");
    return `
      <div class="weekly-wrap">
        <div class="detail-heading">
          <div><strong>Game-by-game projections</strong><span>${data.forecastType === "preseason" ? `${data.projectionSeason} current preseason forecast` : `${data.projectionSeason} out-of-sample validation`}</span></div>
          <small>${data.hasActuals ? `Actual reflects the completed ${data.projectionSeason} validation result` : "Actual points populate after games are completed"}</small>
        </div>
        <div class="weekly-scroll">
          <table class="weekly-table">
            <thead><tr><th>Week</th><th>Matchup</th><th class="number-cell">Projected</th><th class="number-cell actual-column">Actual</th>${headers}</tr></thead>
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

  function playerRow(player, recommendations, actualMetrics) {
    const status = statusFor(player.id);
    const expanded = state.expanded === player.id;
    const rowClass = status === "available" ? "" : ` ${status}`;
    const recommendation = recommendations.byId.get(player.id);
    const liveRank = recommendation?.rank || recommendations.metrics.get(player.id).rank;
    const hindsight = actualMetrics?.get(player.id);
    const displayedDraftValue = state.sort === "actual_draft" && hindsight ? hindsight.value : (recommendation?.nextTurnGap ?? recommendations.metrics.get(player.id).value);
    return `
      <tr class="player-row${rowClass}" data-id="${escapeHtml(player.id)}">
        <td class="rank-cell">
          <div class="rank-pair">
            <span><strong>${liveRank}</strong><small>Live</small></span>
            <span class="actual-rank"><strong>${hindsight?.rank || "-"}</strong><small>Hindsight</small></span>
          </div>
        </td>
        <td class="rank-cell">
          <div class="rank-pair">
            <span><strong>${player.rank}</strong><small>Model</small></span>
            <span class="actual-rank"><strong>${data.hasActuals ? player.actualRank : "-"}</strong><small>Actual</small></span>
          </div>
        </td>
        <td>
          <div class="player-cell">
            <img src="${teamLogo(player.team)}" alt="" onerror="this.hidden=true">
            <span><strong>${escapeHtml(player.name)}</strong><small>${player.projectedGames} projected games${player.depthRank ? ` · depth ${player.position}${player.depthRank}` : ""}${player.projectionNote && player.projectionNote !== "none" ? ` · ${escapeHtml(player.projectionNote)}` : ""}</small></span>
          </div>
        </td>
        <td><span class="${positionClass(player.position)}">${escapeHtml(player.position)}</span></td>
        <td class="team-cell">${escapeHtml(player.team)}</td>
        <td class="number-cell projection"><strong>${player.projectedPoints.toFixed(1)}</strong></td>
        <td class="number-cell actual-total actual-column">${data.hasActuals ? player.actualPoints.toFixed(1) : "-"}</td>
        <td class="number-cell">${player.pointsPerGame.toFixed(2)}</td>
        <td class="number-cell draft-value" title="${state.sort === "actual_draft" ? "Hindsight value over the format-derived replacement player" : "Projected-point gap to the best same-position player expected to survive until your next turn"}">${displayedDraftValue > 0 ? "+" : ""}${displayedDraftValue.toFixed(1)}</td>
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
          <td colspan="11">${playerDetail(player)}</td>
        </tr>
      ` : ""}
    `;
  }

  function rosterNeeds() {
    const slots = defaultConfig.rosterSlots;
    const mine = data.players.filter((player) => statusFor(player.id) === "mine");
    const counts = mine.reduce((result, player) => ({ ...result, [player.position]: (result[player.position] || 0) + 1 }), {});
    const base = ["QB", "RB", "WR", "TE", "K"].map((position) => {
      const needed = Math.max(0, slots[position] - (counts[position] || 0));
      return `<span class="need-chip${needed ? " open" : " filled"}">${position} ${counts[position] || 0}/${slots[position]}</span>`;
    });
    const flexEligible = ["RB", "WR", "TE"].reduce((total, position) => total + (counts[position] || 0), 0);
    const baseFlexUsed = ["RB", "WR", "TE"].reduce((total, position) => total + Math.min(counts[position] || 0, slots[position]), 0);
    const flexFilled = Math.min(slots.FLEX, Math.max(0, flexEligible - baseFlexUsed));
    base.splice(4, 0, `<span class="need-chip${flexFilled < slots.FLEX ? " open" : " filled"}">FLEX ${flexFilled}/${slots.FLEX}</span>`);
    return base.join("");
  }

  function renderSummary(recommendations) {
    const best = recommendations.candidates[0]?.player;
    const bestRecommendation = best ? recommendations.byId.get(best.id) : null;
    $("bestName").textContent = best?.name || "No player available";
    $("bestMeta").textContent = best ? `${best.position} · ${best.team} · ${bestRecommendation.likelyGone ? "unlikely to reach next turn" : "may reach next turn"}` : "-";
    $("bestPoints").textContent = bestRecommendation ? `${bestRecommendation.nextTurnGap >= 0 ? "+" : ""}${bestRecommendation.nextTurnGap.toFixed(1)}` : "-";
    $("bestMetricLabel").textContent = "Next-turn gap";
    $("bestMetricUnit").textContent = `vs best ${best?.position || "position"} expected at pick ${recommendations.nextTurn}`;
    $("availableCount").textContent = data.players.filter((player) => statusFor(player.id) === "available").length;
    $("mineCount").textContent = data.players.filter((player) => statusFor(player.id) === "mine").length;
    $("takenCount").textContent = data.players.filter((player) => statusFor(player.id) === "other").length;
    const round = Math.floor((recommendations.currentPick - 1) / state.teams) + 1;
    $("clockPick").textContent = `${round}.${String(((recommendations.currentPick - 1) % state.teams) + 1).padStart(2, "0")}`;
    $("clockMeta").textContent = recommendations.onClock ? "You are on the clock" : `Team ${snakeTeam(recommendations.currentPick)} selecting`;
    $("nextTurn").textContent = `#${recommendations.nextTurn}`;
    $("nextTurnMeta").textContent = `${recommendations.opponentPicks} opponent picks away`;
    $("rosterNeeds").innerHTML = rosterNeeds();
    $("undoButton").disabled = state.picks.length === 0;
  }

  function render() {
    const recommendations = recommendationState();
    const actualMetrics = data.hasActuals ? formatMetrics("actualPoints") : null;
    const players = filteredPlayers(recommendations, actualMetrics);
    $("rankingsBody").innerHTML = players.map((player) => playerRow(player, recommendations, actualMetrics)).join("");
    $("emptyState").hidden = players.length > 0;
    renderSummary(recommendations);
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
    $("teamsSelect").addEventListener("change", (event) => {
      state.teams = Number(event.target.value);
      state.draftSlot = Math.min(state.draftSlot, state.teams);
      $("slotInput").max = state.teams;
      $("slotInput").value = state.draftSlot;
      savePicks();
      render();
    });
    $("slotInput").addEventListener("change", (event) => {
      state.draftSlot = Math.max(1, Math.min(state.teams, Number(event.target.value) || 1));
      event.target.value = state.draftSlot;
      savePicks();
      render();
    });
    $("scenarioSelect").addEventListener("change", (event) => {
      state.scenario = event.target.value;
      savePicks();
      render();
    });
    $("policySelect").addEventListener("change", (event) => {
      state.policy = event.target.value;
      savePicks();
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
    $("teamsSelect").value = String(state.teams);
    $("slotInput").max = state.teams;
    $("slotInput").value = state.draftSlot;
    $("scenarioSelect").value = state.scenario;
    $("policySelect").value = state.policy;
    $("seasonLabel").textContent = data.forecastType === "preseason" ? `${data.projectionSeason} preseason` : `${data.projectionSeason} validation season`;
    $("modelStatus").textContent = `${data.scoring} · ${data.forecastType === "preseason" ? "current forecast" : "development model"}`;
    $("methodLabel").textContent = data.forecastType === "preseason"
      ? `${data.scope}. Frozen model choices refit through ${data.trainingThrough}; current active roster, depth chart, schedule, and game lines as of ${new Date(data.dataAsOf).toLocaleString()}.`
      : `${data.scope}. Recommendations combine game-level forecasts, format-derived replacement value, your roster, and the projected pool at your next snake turn; this remains a ${data.projectionSeason} out-of-sample validation board, not a live ${new Date().getFullYear()} preseason ranking.`;
    $("footerScope").textContent = `${data.projectionSeason} · ${data.scoring} · ${data.players.length} fantasy-relevant players`;
    const generated = new Date(data.generatedAt);
    $("updatedLabel").textContent = `Generated ${generated.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
    if (!data.hasActuals) {
      document.body.classList.add("no-actuals");
      $("draftRankSub").textContent = "Live recommendation";
      $("pointsRankSub").textContent = "Model";
      $("sortSelect").querySelectorAll('option[value="actual"], option[value="actual_draft"]').forEach((option) => { option.hidden = true; option.disabled = true; });
    }
    bindEvents();
    render();
    $("app").hidden = false;
  }

  window.addEventListener("DOMContentLoaded", boot);
})();
