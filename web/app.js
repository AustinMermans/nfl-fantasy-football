(() => {
  "use strict";

  const data = window.NFL_DRAFT_DATA;
  const storageKey = "nfl-fantasy-draft-board-v4";
  const previousStorageKey = "nfl-fantasy-draft-board-v3";
  const legacyStorageKey = "nfl-fantasy-draft-board-v1";
  const defaultConfig = data?.draftConfig || {
    teams: 12, draftSlot: 1, rosterSlots: { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1 },
  };
  const baseScoring = data?.scoringWeights || {
    passing_yards: 0.04, passing_tds: 4, passing_interceptions: -2,
    rushing_yards: 0.1, rushing_tds: 6, receptions: 0,
    receiving_yards: 0.1, receiving_tds: 6, fumbles_lost_total: -2,
  };
  const state = {
    position: "ALL", query: "", sort: "draft", picks: [], expanded: null,
    teams: Number(defaultConfig.teams || 12), draftSlot: Number(defaultConfig.draftSlot || 1), scenario: "adaptive", policy: "lookahead",
    scoring: { ...baseScoring },
  };
  let recommendationCache = { key: null, value: null };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);

  const positionClass = (position) => `position position-${position.toLowerCase()}`;
  const pointsFor = (player) => {
    if (Number.isFinite(player?._points)) return player._points;
    return Number(player?.projectedPoints || 0)
      + (Number(state.scoring.receptions) - Number(baseScoring.receptions || 0)) * Number(player?.stats?.receptions || 0)
      + (Number(state.scoring.passing_tds) - Number(baseScoring.passing_tds || 0)) * Number(player?.stats?.passing_tds || 0)
      + (Number(state.scoring.passing_interceptions) - Number(baseScoring.passing_interceptions || 0)) * Number(player?.stats?.passing_interceptions || 0);
  };
  const gamePointsFor = (game) => Number(game?.projectedPoints || 0)
    + (Number(state.scoring.receptions) - Number(baseScoring.receptions || 0)) * Number(game?.stats?.receptions || 0)
    + (Number(state.scoring.passing_tds) - Number(baseScoring.passing_tds || 0)) * Number(game?.stats?.passing_tds || 0)
    + (Number(state.scoring.passing_interceptions) - Number(baseScoring.passing_interceptions || 0)) * Number(game?.stats?.passing_interceptions || 0);
  const scoringName = () => {
    const reception = Number(state.scoring.receptions || 0);
    const receptionName = reception === 1 ? "Full PPR" : reception === 0.5 ? "Half PPR" : "Standard";
    return `${receptionName} · ${state.scoring.passing_tds}-pt pass TD`;
  };
  const teamLogo = (team) => {
    const aliases = { JAX: "jax", LA: "lar", WAS: "wsh" };
    return `https://a.espncdn.com/i/teamlogos/nfl/500/${aliases[team] || team.toLowerCase()}.png`;
  };

  function loadPicks() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || localStorage.getItem(previousStorageKey));
      if (saved && Array.isArray(saved.picks)) {
        state.picks = saved.picks.filter((pick) => pick.id && pick.owner);
        state.teams = Number(saved.teams || state.teams);
        state.draftSlot = Math.min(state.teams, Number(saved.draftSlot || state.draftSlot));
        state.scenario = saved.scenario || state.scenario;
        state.policy = saved.policy || state.policy;
        state.scoring = { ...state.scoring, ...(saved.scoring || {}) };
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
      picks: state.picks, teams: state.teams, draftSlot: state.draftSlot, scenario: state.scenario, policy: state.policy, scoring: state.scoring,
    }));
  }

  function statusFor(id) {
    return [...state.picks].reverse().find((pick) => pick.id === id)?.owner || "available";
  }

  function setPlayerStatus(id, owner) {
    state.picks = state.picks.filter((pick) => pick.id !== id);
    if (owner !== "available") {
      const overallPick = state.picks.length + 1;
      state.picks.push({ id, owner, overallPick, drafterTeam: owner === "mine" ? state.draftSlot : snakeTeam(overallPick), changedAt: Date.now() });
    }
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

  function starterCounts(pointValue = pointsFor) {
    const slots = defaultConfig.rosterSlots;
    const counts = { QB: state.teams * slots.QB, RB: state.teams * slots.RB, WR: state.teams * slots.WR, TE: state.teams * slots.TE, K: state.teams * slots.K };
    const flexPool = ["RB", "WR", "TE"].flatMap((position) => data.players
      .filter((player) => player.position === position)
      .sort((a, b) => pointValue(b) - pointValue(a))
      .slice(counts[position])
      .map((player) => ({ player, points: pointValue(player) })));
    flexPool.sort((a, b) => b.points - a.points);
    flexPool.slice(0, state.teams * slots.FLEX).forEach(({ player }) => { counts[player.position] += 1; });
    return counts;
  }

  function formatMetrics(pointValue = pointsFor) {
    const counts = starterCounts(pointValue);
    const replacements = {};
    Object.keys(counts).forEach((position) => {
      const ordered = data.players.filter((player) => player.position === position).sort((a, b) => pointValue(b) - pointValue(a));
      const replacement = ordered[Math.min(Math.max(counts[position], 1), ordered.length) - 1];
      replacements[position] = replacement ? pointValue(replacement) : 0;
    });
    const ordered = data.players.map((player) => ({
      player, value: pointValue(player) - replacements[player.position], replacement: replacements[player.position],
    })).sort((a, b) => b.value - a.value || pointValue(b.player) - pointValue(a.player) || a.player.name.localeCompare(b.player.name));
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
        .sort((a, b) => pointsFor(b) - pointsFor(a))
        .slice(0, slots[position])
        .forEach((player) => { selected.add(player.id); total += pointsFor(player); });
    });
    players.filter((player) => ["RB", "WR", "TE"].includes(player.position) && !selected.has(player.id))
      .sort((a, b) => pointsFor(b) - pointsFor(a))
      .slice(0, slots.FLEX)
      .forEach((player) => { total += pointsFor(player); });
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
        _points: replacements[position] || 0,
      })));
    return optimalLineupValue([...players, ...replacementPlayers]);
  }

  function scaledRange(player) {
    const range = player.projectionRange || {};
    const current = pointsFor(player);
    const base = Number(player.projectedPoints || 0);
    const scale = base > 0 ? current / base : 1;
    return {
      p10: Number(range.p10 ?? base) * scale,
      p50: Number(range.p50 ?? base) * scale,
      p90: Number(range.p90 ?? base) * scale,
      source: range.source || "point forecast",
      effectiveSample: Number(range.effectiveSample || 0),
    };
  }

  function rookieOptionValue(player, replacement) {
    const range = scaledRange(player);
    if (range.source !== "historical rookie analogs") return 0;
    const expectedBest = 0.25 * Math.max(range.p10, replacement)
      + 0.5 * Math.max(range.p50, replacement)
      + 0.25 * Math.max(range.p90, replacement);
    return Math.max(0, expectedBest - Math.max(pointsFor(player), replacement));
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

  function seededRandom(seed) {
    let value = seed >>> 0;
    return () => {
      value += 0x6D2B79F5;
      let result = value;
      result = Math.imul(result ^ (result >>> 15), result | 1);
      result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
      return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
    };
  }

  function observedRosterCounts() {
    const rosters = new Map();
    state.picks.forEach((pick, index) => {
      const team = Number(pick.drafterTeam || snakeTeam(pick.overallPick || index + 1));
      const player = data.players.find((item) => item.id === pick.id);
      if (!player) return;
      const counts = rosters.get(team) || {};
      counts[player.position] = (counts[player.position] || 0) + 1;
      rosters.set(team, counts);
    });
    return rosters;
  }

  function opponentUtility(player, overallPick, manager, metrics, rosters) {
    const round = Math.floor((overallPick - 1) / state.teams) + 1;
    const counts = rosters.get(manager) || {};
    const slots = defaultConfig.rosterSlots;
    let utility = -0.075 * metrics.get(player.id).rank;
    if (player.position === "K" && round < Number(defaultConfig.rounds || 12)) utility -= 12;
    if ((counts[player.position] || 0) < (slots[player.position] || 0)) utility += 1.0;
    if (["QB", "TE", "K"].includes(player.position) && (counts[player.position] || 0) >= (slots[player.position] || 0)) utility -= 0.9;
    if (["RB", "WR"].includes(player.position)) utility += 0.18;
    const run = runPosition();
    if (run === player.position && (state.scenario === "adaptive" || round <= 2)) utility += 0.75;
    return utility;
  }

  function stochasticOpponentPicks(available, candidateId, count, afterPick, metrics, seed) {
    const marketPool = available
      .filter((player) => player.id !== candidateId)
      .sort((a, b) => metrics.get(a.id).rank - metrics.get(b.id).rank)
      .slice(0, 180);
    const deepPool = available.filter((player) => !marketPool.includes(player) && player.id !== candidateId);
    const rosters = observedRosterCounts();
    const random = seededRandom(seed);
    const removed = [];
    for (let index = 0; index < count && marketPool.length; index += 1) {
      const overallPick = afterPick + index + 1;
      const manager = snakeTeam(overallPick);
      const utilities = marketPool.map((player) => opponentUtility(player, overallPick, manager, metrics, rosters));
      const anchor = Math.max(...utilities);
      const weights = utilities.map((utility) => Math.exp(utility - anchor));
      const threshold = random() * weights.reduce((sum, value) => sum + value, 0);
      let cumulative = 0;
      let chosenIndex = weights.length - 1;
      for (let poolIndex = 0; poolIndex < weights.length; poolIndex += 1) {
        cumulative += weights[poolIndex];
        if (cumulative >= threshold) { chosenIndex = poolIndex; break; }
      }
      const [chosen] = marketPool.splice(chosenIndex, 1);
      removed.push(chosen);
      const counts = rosters.get(manager) || {};
      counts[chosen.position] = (counts[chosen.position] || 0) + 1;
      rosters.set(manager, counts);
    }
    return { survivors: [...marketPool, ...deepPool], removed };
  }

  function recommendationState() {
    const cacheKey = JSON.stringify({ picks: state.picks, teams: state.teams, draftSlot: state.draftSlot, scenario: state.scenario, policy: state.policy, scoring: state.scoring });
    if (recommendationCache.key === cacheKey) return recommendationCache.value;
    const available = data.players.filter((player) => statusFor(player.id) === "available");
    const myRoster = data.players.filter((player) => statusFor(player.id) === "mine");
    const metrics = formatMetrics();
    const currentPick = state.picks.length + 1;
    const onClock = snakeTeam(currentPick) === state.draftSlot;
    const decisionPick = onClock ? currentPick : nextPickForTeam(currentPick - 1);
    const nextTurn = nextPickForTeam(decisionPick);
    const opponentPicks = nextTurn - decisionPick - 1;
    const simulationCount = 16;
    const seeds = Array.from({ length: simulationCount }, (_, index) => 104729 + index * 1543 + state.picks.length * 37);
    const baselineSurvival = new Map(available.map((player) => [player.id, 0]));
    seeds.forEach((seed) => {
      const survivors = new Set(stochasticOpponentPicks(available, "", opponentPicks, decisionPick, metrics, seed).survivors.map((player) => player.id));
      available.forEach((player) => { if (survivors.has(player.id)) baselineSurvival.set(player.id, baselineSurvival.get(player.id) + 1); });
    });
    const shortlist = new Set([
      ...available.sort((a, b) => metrics.get(a.id).rank - metrics.get(b.id).rank).slice(0, 48).map((player) => player.id),
      ...["QB", "RB", "WR", "TE", "K"].flatMap((position) => available
        .filter((player) => player.position === position)
        .sort((a, b) => metrics.get(a.id).rank - metrics.get(b.id).rank)
        .slice(0, 6).map((player) => player.id)),
    ]);
    const withoutCandidate = rosterValue(myRoster, metrics);
    const candidates = available.map((candidate) => {
      const immediateValue = rosterValue([...myRoster, candidate], metrics)
        + rookieOptionValue(candidate, metrics.get(candidate.id).replacement);
      const currentRound = Math.floor((decisionPick - 1) / state.teams) + 1;
      const timingEligible = candidate.position !== "K" || currentRound >= Number(defaultConfig.rounds || 12);
      let decisionValue = immediateValue;
      if (state.policy === "lookahead" && shortlist.has(candidate.id) && opponentPicks > 0) {
        let total = 0;
        seeds.forEach((seed) => {
          const simulation = stochasticOpponentPicks(available, candidate.id, opponentPicks, decisionPick, metrics, seed);
          const nextOptions = ["QB", "RB", "WR", "TE", "K"].map((position) => simulation.survivors
            .filter((player) => player.position === position)
            .sort((a, b) => pointsFor(b) - pointsFor(a))[0]).filter(Boolean);
          const bestContinuation = nextOptions.length
            ? Math.max(...nextOptions.map((nextPlayer) => rosterValue([...myRoster, candidate, nextPlayer], metrics)
              + rookieOptionValue(candidate, metrics.get(candidate.id).replacement)
              + rookieOptionValue(nextPlayer, metrics.get(nextPlayer.id).replacement)))
            : immediateValue;
          total += bestContinuation;
        });
        decisionValue = total / simulationCount;
      }
      return {
        player: candidate,
        decisionValue,
        immediateValue,
        protectedGain: decisionValue - withoutCandidate,
        survivalProbability: Number(baselineSurvival.get(candidate.id) || 0) / simulationCount,
        baseValue: metrics.get(candidate.id).value,
        timingEligible,
      };
    });
    candidates.sort((a, b) => {
      if (state.policy === "lookahead") {
        return Number(b.timingEligible) - Number(a.timingEligible)
          || b.decisionValue - a.decisionValue
          || b.baseValue - a.baseValue
          || pointsFor(b.player) - pointsFor(a.player);
      }
      return Number(b.timingEligible) - Number(a.timingEligible)
        || b.immediateValue - a.immediateValue
        || b.baseValue - a.baseValue
        || pointsFor(b.player) - pointsFor(a.player);
    });
    candidates.forEach((candidate, index) => { candidate.rank = index + 1; });
    const pointRanks = new Map([...data.players]
      .sort((a, b) => pointsFor(b) - pointsFor(a) || a.name.localeCompare(b.name))
      .map((player, index) => [player.id, index + 1]));
    const result = { candidates, byId: new Map(candidates.map((candidate) => [candidate.player.id, candidate])), currentPick, decisionPick, nextTurn, opponentPicks, onClock, metrics, pointRanks };
    recommendationCache = { key: cacheKey, value: result };
    return result;
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
      points: (a, b) => pointsFor(b) - pointsFor(a) || a.rank - b.rank,
      weekly: (a, b) => (pointsFor(b) / b.projectedGames) - (pointsFor(a) / a.projectedGames) || a.rank - b.rank,
      actual: (a, b) => a.actualRank - b.actualRank,
      position: (a, b) => a.position.localeCompare(b.position) || pointsFor(b) - pointsFor(a),
      lift: (a, b) => b.modelLift - a.modelLift || a.rank - b.rank,
      name: (a, b) => a.name.localeCompare(b.name),
    };
    return players.sort(sorters[state.sort]).slice(0, state.query || state.position !== "ALL" ? 240 : 160);
  }

  function statItems(player) {
    const stats = player.stats;
    const byPosition = {
      QB: [["Pass yd", "passing_yards"], ["Pass TD", "passing_tds"], ["INT", "passing_interceptions"], ["Rush yd", "rushing_yards"], ["Rush TD", "rushing_tds"]],
      RB: [["Rush yd", "rushing_yards"], ["Rush TD", "rushing_tds"], ["Rec", "receptions"], ["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"], ["Fumbles", "fumbles_lost_total"]],
      WR: [["Rec", "receptions"], ["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"], ["Rush yd", "rushing_yards"], ["Rush TD", "rushing_tds"], ["Fumbles", "fumbles_lost_total"]],
      TE: [["Rec", "receptions"], ["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"], ["Fumbles", "fumbles_lost_total"]],
      K: [["PAT", "pat_made"], ["FG 0-19", "fg_made_0_19"], ["FG 20-29", "fg_made_20_29"], ["FG 30-39", "fg_made_30_39"], ["FG 40-49", "fg_made_40_49"], ["FG 50+", "fg_made_50_59"]],
    };
    return (byPosition[player.position] || byPosition.WR).map(([label, key]) => `
      <div><span>${label}</span><strong>${Number(stats[key] || 0).toFixed(1)}</strong></div>
    `).join("");
  }

  function gameColumns(position) {
    const columns = {
      QB: [["Pass yd", "passing_yards"], ["Pass TD", "passing_tds"], ["INT", "passing_interceptions"], ["Rush yd", "rushing_yards"]],
      RB: [["Rush yd", "rushing_yards"], ["Rush TD", "rushing_tds"], ["Rec", "receptions"], ["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"]],
      WR: [["Rec", "receptions"], ["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"], ["Rush yd", "rushing_yards"]],
      TE: [["Rec", "receptions"], ["Rec yd", "receiving_yards"], ["Rec TD", "receiving_tds"]],
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
        <td class="number-cell weekly-projection">${gamePointsFor(game).toFixed(2)}</td>
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
    const range = scaledRange(player);
    const injury = [player.injury?.gameStatus, player.injury?.practiceStatus, player.injury?.bodyPart].filter(Boolean).join(" · ");
    const rangeMarkup = range.source === "historical rookie analogs" ? `
      <div class="forecast-range">
        <div><span>Rookie floor P10</span><strong>${range.p10.toFixed(1)}</strong></div>
        <div><span>Median P50</span><strong>${range.p50.toFixed(1)}</strong></div>
        <div><span>Upside P90</span><strong>${range.p90.toFixed(1)}</strong></div>
        <div><span>Effective analogs</span><strong>${range.effectiveSample.toFixed(0)}</strong></div>
      </div>` : "";
    return `
      <div class="player-detail">
        <div class="season-components">
          <span class="detail-label">Projected season components</span>
          <div class="stat-grid">${statItems(player)}</div>
          ${rangeMarkup}
          ${injury ? `<span class="detail-label">Injury report · ${escapeHtml(injury)}</span>` : ""}
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
    const displayedDraftValue = state.sort === "actual_draft" && hindsight ? hindsight.value : recommendation?.survivalProbability;
    const projectedPoints = pointsFor(player);
    const range = scaledRange(player);
    const rookieMeta = range.source === "historical rookie analogs" ? ` · rookie P10–P90 ${range.p10.toFixed(0)}–${range.p90.toFixed(0)}` : "";
    const injuryMeta = player.injury?.gameStatus ? ` · ${escapeHtml(player.injury.gameStatus)}` : "";
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
            <span><strong>${recommendations.pointRanks.get(player.id)}</strong><small>Model</small></span>
            <span class="actual-rank"><strong>${data.hasActuals ? player.actualRank : "-"}</strong><small>Actual</small></span>
          </div>
        </td>
        <td>
          <div class="player-cell">
            <img src="${teamLogo(player.team)}" alt="" onerror="this.hidden=true">
            <span><strong>${escapeHtml(player.name)}</strong><small>${player.projectedGames} projected games${player.depthRank ? ` · depth ${player.position}${player.depthRank}` : ""}${rookieMeta}${injuryMeta}</small></span>
          </div>
        </td>
        <td><span class="${positionClass(player.position)}">${escapeHtml(player.position)}</span></td>
        <td class="team-cell">${escapeHtml(player.team)}</td>
        <td class="number-cell projection"><strong>${projectedPoints.toFixed(1)}</strong></td>
        <td class="number-cell actual-total actual-column">${data.hasActuals ? player.actualPoints.toFixed(1) : "-"}</td>
        <td class="number-cell">${(projectedPoints / player.projectedGames).toFixed(2)}</td>
        <td class="number-cell draft-value" title="${state.sort === "actual_draft" ? "Hindsight value over the format-derived replacement player" : "Estimated probability of surviving to your next pick under the selected opponent scenario"}">${state.sort === "actual_draft" ? `${displayedDraftValue > 0 ? "+" : ""}${displayedDraftValue.toFixed(1)}` : recommendation ? `${Math.round(displayedDraftValue * 100)}%` : "-"}</td>
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
    $("bestMeta").textContent = best ? `${best.position} · ${best.team} · ${scoringName()}` : "-";
    $("bestPoints").textContent = bestRecommendation ? `${Math.round(bestRecommendation.survivalProbability * 100)}%` : "-";
    $("bestMetricLabel").textContent = "Next-turn survival";
    $("bestMetricUnit").textContent = `16 opponent-pick simulations to #${recommendations.nextTurn}`;
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
    const actualMetrics = data.hasActuals ? formatMetrics((player) => player.actualPoints) : null;
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
    [["receptionSelect", "receptions"], ["passingTdSelect", "passing_tds"], ["interceptionSelect", "passing_interceptions"]].forEach(([id, field]) => {
      $(id).addEventListener("change", (event) => {
        state.scoring[field] = Number(event.target.value);
        savePicks();
        render();
        $("modelStatus").textContent = `${scoringName()} · current forecast`;
        $("footerScope").textContent = `${data.projectionSeason} · ${scoringName()} · ${data.players.length} fantasy-relevant players`;
      });
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
    $("receptionSelect").value = String(state.scoring.receptions);
    $("passingTdSelect").value = String(state.scoring.passing_tds);
    $("interceptionSelect").value = String(state.scoring.passing_interceptions);
    $("seasonLabel").textContent = data.forecastType === "preseason" ? `${data.projectionSeason} preseason` : `${data.projectionSeason} validation season`;
    $("modelStatus").textContent = `${scoringName()} · ${data.forecastType === "preseason" ? "current forecast" : "development model"}`;
    $("methodLabel").textContent = data.forecastType === "preseason"
      ? `${data.scope}. Models refit through ${data.trainingThrough}; active rosters, starter depth, schedule, and game lines as of ${new Date(data.dataAsOf).toLocaleString()}. Recommendations simulate opponent choices and your next snake turn.`
      : `${data.scope}. Recommendations combine game-level forecasts, format-derived replacement value, your roster, and the projected pool at your next snake turn; this remains a ${data.projectionSeason} out-of-sample validation board, not a live ${new Date().getFullYear()} preseason ranking.`;
    $("footerScope").textContent = `${data.projectionSeason} · ${scoringName()} · ${data.players.length} fantasy-relevant players`;
    $("injuryStatus").textContent = data.injuryReportsAvailable
      ? `Current injury report: ${data.injurySource}`
      : "Current injury designations unavailable · missing means unknown";
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
