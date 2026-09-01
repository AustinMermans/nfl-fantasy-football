(() => {
  "use strict";

  const data = window.NFL_DRAFT_DATA;
  const marketData = window.NFL_MARKET_DATA || { players: [] };
  const storageKey = "nfl-fantasy-draft-board-v6";
  const previousStorageKey = "nfl-fantasy-draft-board-v5";
  const legacyStorageKey = "nfl-fantasy-draft-board-v1";
  const defaultConfig = data?.draftConfig || {
    teams: 10, draftSlot: 10, rosterSlots: { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 2, K: 1 },
    rosterMaximums: { QB: 4, RB: 8, WR: 8, TE: 3, K: 3 }, benchSlots: 8, rounds: 17,
  };
  const baseScoring = data?.scoringWeights || {
    passing_yards: 0.04, passing_tds: 4, passing_interceptions: -2,
    rushing_yards: 0.1, rushing_tds: 6, receptions: 0.5,
    receiving_yards: 0.1, receiving_tds: 6, fumbles_lost_total: -2,
  };
  const state = {
    position: "ALL", query: "", sort: "draft", picks: [], expanded: null,
    teams: Number(defaultConfig.teams || 12), draftSlot: Number(defaultConfig.draftSlot || 1), scenario: "adaptive", policy: "lookahead",
    scoring: { ...baseScoring },
  };
  let recommendationCache = { key: null, value: null };
  const roomModels = {
    balanced: { label: "Balanced", prior: 0.40 },
    rb_heavy: { label: "RB-heavy", prior: 0.15 },
    wr_heavy: { label: "WR-heavy", prior: 0.15 },
    early_qb: { label: "Early-QB", prior: 0.15 },
    zero_rb: { label: "Zero-RB", prior: 0.15 },
  };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
  const normalizedName = (value) => String(value || "").toLowerCase().normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "").replace(/\b(jr|sr|ii|iii|iv)\b/g, "").replace(/[^a-z0-9]/g, "");
  const marketByPlayer = new Map((marketData.players || []).map((player) => [
    `${normalizedName(player.name)}|${player.position}`, player,
  ]));
  const marketFor = (player) => marketByPlayer.get(`${normalizedName(player.name)}|${player.position}`);
  const marketRankFor = (player, metrics) => {
    const market = marketFor(player);
    return Number(
      market?.marketCenter
      || market?.adp
      || market?.halfPprRank
      || Math.max(220, metrics.get(player.id).rank),
    );
  };

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
      const currentSaved = localStorage.getItem(storageKey);
      const saved = JSON.parse(currentSaved || localStorage.getItem(previousStorageKey));
      if (saved && Array.isArray(saved.picks)) {
        const validIds = new Set(data.players.map((player) => player.id));
        state.teams = currentSaved && [8, 10, 12, 14, 16].includes(Number(saved.teams)) ? Number(saved.teams) : state.teams;
        state.draftSlot = Math.max(1, Math.min(state.teams, currentSaved ? Number(saved.draftSlot) || state.draftSlot : state.draftSlot));
        const seen = new Set();
        state.picks = saved.picks.filter((pick) => validIds.has(pick.id) && ["mine", "other"].includes(pick.owner) && !seen.has(pick.id) && seen.add(pick.id))
          .slice(0, state.teams * Number(defaultConfig.rounds || 12))
          .map((pick, index) => ({ ...pick, overallPick: index + 1, drafterTeam: pick.owner === "mine" ? state.draftSlot : snakeTeam(index + 1) }));
        if (currentSaved) {
          state.scenario = saved.scenario || state.scenario;
          state.policy = saved.policy || state.policy;
          state.scoring = { ...state.scoring, ...(saved.scoring || {}) };
        }
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
    if (owner === "available" || statusFor(id) !== "available") return;
    const maxPicks = state.teams * Number(defaultConfig.rounds || 12);
    if (state.picks.length >= maxPicks) return;
    const overallPick = state.picks.length + 1;
    state.picks.push({ id, owner, overallPick, drafterTeam: owner === "mine" ? state.draftSlot : snakeTeam(overallPick), changedAt: Date.now() });
    savePicks();
    render();
    const player = data.players.find((item) => item.id === id);
    $("announcement").textContent = `${player?.name || "Player"} marked ${owner === "mine" ? "on your roster" : "taken"}. Undo is available.`;
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

  function hashUniform(value) {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return ((hash >>> 0) + 0.5) / 4294967296;
  }

  function standardNormal(key) {
    const first = Math.max(hashUniform(`${key}-a`), 1e-9);
    const second = hashUniform(`${key}-b`);
    return Math.sqrt(-2 * Math.log(first)) * Math.cos(2 * Math.PI * second);
  }

  function rookieRoleMultiplier(player, scenario) {
    const range = scaledRange(player);
    if (range.source !== "historical rookie analogs") return 1;
    const average = 0.3 * range.p10 + 0.4 * range.p50 + 0.3 * range.p90;
    if (average <= 0) return 1;
    const draw = hashUniform(`${player.id}-${scenario}-rookie`);
    let outcome;
    if (draw <= 0.1) outcome = range.p10;
    else if (draw < 0.5) outcome = range.p10 + ((draw - 0.1) / 0.4) * (range.p50 - range.p10);
    else if (draw < 0.9) outcome = range.p50 + ((draw - 0.5) / 0.4) * (range.p90 - range.p50);
    else outcome = range.p90;
    return outcome / average;
  }

  function injuryDuration(meanDuration, key) {
    const mean = Math.max(1, Number(meanDuration || 1));
    const success = 1 / mean;
    if (success >= 1) return 1;
    return Math.min(8, Math.ceil(Math.log(1 - hashUniform(key)) / Math.log(1 - success)));
  }

  function currentInjuryProbability(player) {
    const status = String(player.injury?.gameStatus || "").toLowerCase();
    if (status === "out") return 1;
    if (status === "doubtful") return 0.75;
    if (status === "questionable") return 0.25;
    return 0;
  }

  function buildWeeklyOutcomes(metrics) {
    const weeks = Number(data.benchModel?.weeks || 18);
    const simulations = Number(data.benchModel?.simulations || 12);
    const parameters = data.benchModel?.parametersByPosition || {};
    const outcomes = new Map();
    data.players.forEach((player) => {
      const games = new Map(player.games.map((game) => [Number(game.week), game]));
      const injuryRisk = player.injuryRisk || {};
      const weeklyHazard = Math.min(0.08, Math.max(0.005, Number(injuryRisk.weeklyHazard || 0.025)));
      const meanDuration = Math.min(6, Math.max(1, Number(injuryRisk.meanDuration || 2)));
      const availability = new Uint8Array(weeks * simulations);
      let availableGames = 0;
      let scheduledGames = 0;
      for (let scenario = 0; scenario < simulations; scenario += 1) {
        let injuryWeeksRemaining = hashUniform(`${player.id}-${scenario}-current-injury`) < currentInjuryProbability(player)
          ? injuryDuration(meanDuration, `${player.id}-${scenario}-current-duration`) : 0;
        for (let week = 1; week <= weeks; week += 1) {
          const index = scenario * weeks + week - 1;
          const hasGame = games.has(week);
          if (hasGame) scheduledGames += 1;
          if (injuryWeeksRemaining > 0) {
            injuryWeeksRemaining -= 1;
            continue;
          }
          if (hasGame && hashUniform(`${player.id}-${scenario}-${week}-injury`) < weeklyHazard) {
            injuryWeeksRemaining = injuryDuration(meanDuration, `${player.id}-${scenario}-${week}-duration`) - 1;
            continue;
          }
          availability[index] = 1;
          if (hasGame) availableGames += 1;
        }
      }
      const healthyScale = availableGames > 0 ? scheduledGames / availableGames : 1;
      const positionError = Math.min(0.9, Math.max(0.25, Number(parameters[player.position]?.relativeError68 || 0.6)));
      const logSigma = Math.sqrt(Math.log(1 + positionError ** 2));
      const values = new Float64Array(weeks * simulations);
      for (let scenario = 0; scenario < simulations; scenario += 1) {
        const roleMultiplier = rookieRoleMultiplier(player, scenario);
        for (let week = 1; week <= weeks; week += 1) {
          const game = games.get(week);
          const index = scenario * weeks + week - 1;
          if (!game || !availability[index]) continue;
          const mean = Math.max(0, gamePointsFor(game)) * roleMultiplier * healthyScale;
          const noise = Math.exp(logSigma * standardNormal(`${player.id}-${scenario}-${week}`) - 0.5 * logSigma ** 2);
          values[index] = mean * noise;
        }
      }
      outcomes.set(player.id, values);
    });
    const replacements = Object.fromEntries(["QB", "RB", "WR", "TE", "K"].map((position) => {
      const player = data.players.find((item) => item.position === position);
      return [position, player ? metrics.get(player.id).replacement / 17 : 0];
    }));
    return { outcomes, replacements, weeks, simulations };
  }

  function weeklyLineupValue(players, index, weekly) {
    const slots = defaultConfig.rosterSlots;
    const buckets = Object.fromEntries(["QB", "RB", "WR", "TE", "K"].map((position) => [position, []]));
    players.forEach((player) => buckets[player.position]?.push(weekly.outcomes.get(player.id)?.[index] || 0));
    Object.keys(buckets).forEach((position) => {
      const count = Number(slots[position] || 0) + (["RB", "WR", "TE"].includes(position) ? Number(slots.FLEX || 0) : 0);
      buckets[position].push(...Array.from({ length: count }, () => weekly.replacements[position]));
      buckets[position].sort((a, b) => b - a);
    });
    let total = 0;
    const flex = [];
    ["QB", "RB", "WR", "TE", "K"].forEach((position) => {
      total += buckets[position].slice(0, slots[position]).reduce((sum, value) => sum + value, 0);
      if (["RB", "WR", "TE"].includes(position)) flex.push(...buckets[position].slice(slots[position]));
    });
    flex.sort((a, b) => b - a);
    return total + flex.slice(0, slots.FLEX).reduce((sum, value) => sum + value, 0);
  }

  function managedRosterValue(players, weekly, cache) {
    const capacity = Object.values(defaultConfig.rosterSlots).reduce((sum, value) => sum + Number(value), 0)
      + Number(defaultConfig.benchSlots || 4);
    if (players.length > capacity) {
      return Math.max(...players.map((_, index) => managedRosterValue(
        players.filter((_player, playerIndex) => playerIndex !== index), weekly, cache,
      )));
    }
    const key = players.map((player) => player.id).sort().join("|");
    if (cache.has(key)) return cache.get(key);
    let total = 0;
    for (let scenario = 0; scenario < weekly.simulations; scenario += 1) {
      for (let week = 0; week < weekly.weeks; week += 1) {
        total += weeklyLineupValue(players, scenario * weekly.weeks + week, weekly);
      }
    }
    const expected = total / weekly.simulations;
    cache.set(key, expected);
    return expected;
  }

  function archetypeBonus(archetype, position, round) {
    if (archetype === "rb_heavy") return position === "RB" && round <= 4 ? 2.5 : 0;
    if (archetype === "wr_heavy") return position === "WR" && round <= 4 ? 2.5 : 0;
    if (archetype === "early_qb") return position === "QB" && round <= 4 ? 2.7 : 0;
    if (archetype === "zero_rb" && round <= 5) {
      if (position === "RB") return -1.6;
      if (position === "WR") return 0.75;
      if (position === "TE") return 0.25;
    }
    return 0;
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

  function opponentUtility(player, overallPick, manager, metrics, rosters, archetype) {
    const round = Math.floor((overallPick - 1) / state.teams) + 1;
    const counts = rosters.get(manager) || {};
    const slots = defaultConfig.rosterSlots;
    let utility = -0.28 * marketRankFor(player, metrics) - 0.01 * metrics.get(player.id).rank;
    if (player.position === "K" && round < Number(defaultConfig.rounds || 12)) utility -= 12;
    if ((counts[player.position] || 0) < (slots[player.position] || 0)) utility += 1.0;
    if (["QB", "TE", "K"].includes(player.position) && (counts[player.position] || 0) >= (slots[player.position] || 0)) utility -= 0.9;
    if (["RB", "WR"].includes(player.position)) utility += 0.18;
    utility += archetypeBonus(archetype, player.position, round);
    return utility;
  }

  function normalizedPosterior(logProbabilities) {
    const anchor = Math.max(...Object.values(logProbabilities));
    const weights = Object.fromEntries(Object.entries(logProbabilities).map(([name, value]) => [name, Math.exp(value - anchor)]));
    const total = Object.values(weights).reduce((sum, value) => sum + value, 0);
    return Object.fromEntries(Object.entries(weights).map(([name, value]) => [name, value / total]));
  }

  function roomPosterior(metrics) {
    const logs = Object.fromEntries(Object.entries(roomModels).map(([name, model]) => [name, Math.log(model.prior)]));
    const rosters = new Map();
    let pool = [...data.players];
    state.picks.forEach((pick, index) => {
      const player = data.players.find((item) => item.id === pick.id);
      if (!player) return;
      const overallPick = Number(pick.overallPick || index + 1);
      const manager = Number(pick.drafterTeam || snakeTeam(overallPick));
      if (pick.owner === "other") {
        let riskSet = [...pool].sort((a, b) => marketRankFor(a, metrics) - marketRankFor(b, metrics)).slice(0, 220);
        if (!riskSet.some((item) => item.id === player.id)) riskSet.push(player);
        Object.keys(roomModels).forEach((archetype) => {
          const utilities = riskSet.map((item) => opponentUtility(item, overallPick, manager, metrics, rosters, archetype));
          const anchor = Math.max(...utilities);
          const weights = utilities.map((utility) => Math.exp(utility - anchor));
          const total = weights.reduce((sum, value) => sum + value, 0);
          const positionWeight = weights.reduce((sum, value, itemIndex) => sum + (riskSet[itemIndex].position === player.position ? value : 0), 0);
          logs[archetype] += Math.log(Math.max(positionWeight / total, 1e-6));
        });
      }
      const counts = rosters.get(manager) || {};
      counts[player.position] = (counts[player.position] || 0) + 1;
      rosters.set(manager, counts);
      pool = pool.filter((item) => item.id !== player.id);
    });
    return normalizedPosterior(logs);
  }

  function simulationArchetype(posterior, random) {
    const fixed = { balanced: "balanced", rb_rush: "rb_heavy", wr_rush: "wr_heavy", early_qb: "early_qb", zero_rb: "zero_rb" }[state.scenario];
    if (fixed) return fixed;
    const threshold = random();
    let cumulative = 0;
    for (const [name, probability] of Object.entries(posterior)) {
      cumulative += probability;
      if (threshold <= cumulative) return name;
    }
    return "balanced";
  }

  function stochasticOpponentPicks(available, candidateId, count, afterPick, metrics, posterior, seed) {
    const marketPool = available
      .filter((player) => player.id !== candidateId)
      .sort((a, b) => marketRankFor(a, metrics) - marketRankFor(b, metrics))
      .slice(0, 220);
    const deepPool = available.filter((player) => !marketPool.includes(player) && player.id !== candidateId);
    const rosters = observedRosterCounts();
    const random = seededRandom(seed);
    const archetype = simulationArchetype(posterior, random);
    const removed = [];
    for (let index = 0; index < count && marketPool.length; index += 1) {
      const overallPick = afterPick + index + 1;
      const manager = snakeTeam(overallPick);
      const utilities = marketPool.map((player) => opponentUtility(player, overallPick, manager, metrics, rosters, archetype));
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
    const weekly = buildWeeklyOutcomes(metrics);
    const rosterCache = new Map();
    const posterior = roomPosterior(metrics);
    const currentPick = state.picks.length + 1;
    const draftComplete = currentPick > state.teams * Number(defaultConfig.rounds || 12);
    const onClock = snakeTeam(currentPick) === state.draftSlot;
    const decisionPick = onClock ? currentPick : nextPickForTeam(currentPick - 1);
    const nextTurn = nextPickForTeam(decisionPick);
    const prefixPicks = onClock ? 0 : decisionPick - currentPick;
    const opponentPicks = nextTurn - decisionPick - 1;
    const marketSimulationCount = 256;
    const lookaheadSimulationCount = 32;
    const seeds = Array.from({ length: marketSimulationCount }, (_, index) => 104729 + index * 1543 + state.picks.length * 37);
    const baselineCount = onClock ? opponentPicks : prefixPicks;
    const baselineAfterPick = onClock ? decisionPick : currentPick - 1;
    const baselineSurvival = new Map(available.map((player) => [player.id, 0]));
    const baselineSimulations = seeds.map((seed) => stochasticOpponentPicks(
      available, "", baselineCount, baselineAfterPick, metrics, posterior, seed,
    ));
    baselineSimulations.forEach((simulation) => {
      const survivors = new Set(simulation.survivors.map((player) => player.id));
      available.forEach((player) => { if (survivors.has(player.id)) baselineSurvival.set(player.id, baselineSurvival.get(player.id) + 1); });
    });
    const shortlist = new Set([
      ...[...available].sort((a, b) => metrics.get(a.id).rank - metrics.get(b.id).rank).slice(0, 48).map((player) => player.id),
      ...["QB", "RB", "WR", "TE", "K"].flatMap((position) => available
        .filter((player) => player.position === position)
        .sort((a, b) => metrics.get(a.id).rank - metrics.get(b.id).rank)
        .slice(0, 6).map((player) => player.id)),
    ]);
    const withoutCandidate = managedRosterValue(myRoster, weekly, rosterCache);
    const currentRound = Math.floor((decisionPick - 1) / state.teams) + 1;
    const rosterCapacity = Object.values(defaultConfig.rosterSlots).reduce((sum, value) => sum + Number(value), 0)
      + Number(defaultConfig.benchSlots || 4);
    const rosterCounts = myRoster.reduce((counts, player) => ({
      ...counts, [player.position]: (counts[player.position] || 0) + 1,
    }), {});
    const canAddPlayers = (players) => {
      const additions = players.reduce((counts, player) => ({
        ...counts, [player.position]: (counts[player.position] || 0) + 1,
      }), {});
      return Object.entries(additions).every(([position, count]) => (
        (rosterCounts[position] || 0) + count
        <= Number(defaultConfig.rosterMaximums?.[position] || rosterCapacity)
      ));
    };
    const evaluateTurnPair = rosterCapacity - myRoster.length >= 2 && (!onClock || opponentPicks === 0);
    const pairPoolById = new Map([
      ...[...available].sort((a, b) => metrics.get(a.id).rank - metrics.get(b.id).rank).slice(0, 24),
      ...[...available].sort((a, b) => marketRankFor(a, metrics) - marketRankFor(b, metrics)).slice(0, 12),
    ].filter((player) => canAddPlayers([player]) && (player.position !== "K" || currentRound >= Number(defaultConfig.rounds || 12))).map((player) => [player.id, player]));
    const pairPool = evaluateTurnPair ? [...pairPoolById.values()] : [];
    const pairValues = [];
    for (let first = 0; first < pairPool.length; first += 1) {
      for (let second = first + 1; second < pairPool.length; second += 1) {
        const players = [pairPool[first], pairPool[second]];
        if (!canAddPlayers(players)) continue;
        pairValues.push({
          players,
          value: managedRosterValue([...myRoster, ...players], weekly, rosterCache),
        });
      }
    }
    const pairSelections = new Map(available.map((player) => [player.id, 0]));
    const selectedPairs = new Map();
    if (!onClock) {
      baselineSimulations.forEach((simulation) => {
        const survivors = new Set(simulation.survivors.map((player) => player.id));
        const bestPair = pairValues
          .filter((pair) => pair.players.every((player) => survivors.has(player.id)))
          .sort((a, b) => b.value - a.value)[0];
        if (!bestPair) return;
        bestPair.players.forEach((player) => pairSelections.set(player.id, pairSelections.get(player.id) + 1));
        const pairKey = bestPair.players.map((player) => player.id).sort().join("|");
        selectedPairs.set(pairKey, (selectedPairs.get(pairKey) || 0) + 1);
      });
    }
    const candidates = available.map((candidate) => {
      const immediateValue = managedRosterValue([...myRoster, candidate], weekly, rosterCache);
      const underPositionMaximum = (rosterCounts[candidate.position] || 0)
        < Number(defaultConfig.rosterMaximums?.[candidate.position] || rosterCapacity);
      const timingEligible = underPositionMaximum
        && (candidate.position !== "K" || currentRound >= Number(defaultConfig.rounds || 12));
      let decisionValue = immediateValue;
      if (state.policy === "lookahead" && onClock && shortlist.has(candidate.id) && opponentPicks === 0) {
        decisionValue = Math.max(
          immediateValue,
          ...pairPool.filter((partner) => partner.id !== candidate.id).map((partner) => managedRosterValue(
            [...myRoster, candidate, partner], weekly, rosterCache,
          )),
        );
      } else if (state.policy === "lookahead" && onClock && shortlist.has(candidate.id) && opponentPicks > 0) {
        let total = 0;
        seeds.slice(0, lookaheadSimulationCount).forEach((seed) => {
          const simulation = stochasticOpponentPicks(available, candidate.id, opponentPicks, decisionPick, metrics, posterior, seed);
          const nextOptions = ["QB", "RB", "WR", "TE", "K"].map((position) => simulation.survivors
            .filter((player) => player.position === position)
            .sort((a, b) => pointsFor(b) - pointsFor(a))[0]).filter(Boolean);
          const bestContinuation = nextOptions.length
            ? Math.max(...nextOptions.map((nextPlayer) => managedRosterValue(
              [...myRoster, candidate, nextPlayer], weekly, rosterCache,
            )))
            : immediateValue;
          total += bestContinuation;
        });
        decisionValue = total / lookaheadSimulationCount;
      }
      return {
        player: candidate,
        decisionValue,
        immediateValue,
        immediateGain: immediateValue - withoutCandidate,
        protectedGain: decisionValue - withoutCandidate,
        survivalProbability: Number(baselineSurvival.get(candidate.id) || 0) / marketSimulationCount,
        pairSelectionProbability: Number(pairSelections.get(candidate.id) || 0) / marketSimulationCount,
        baseValue: metrics.get(candidate.id).value,
        timingEligible,
      };
    });
    candidates.sort((a, b) => {
      if (!onClock) {
        return Number(b.timingEligible) - Number(a.timingEligible)
          || b.pairSelectionProbability - a.pairSelectionProbability
          || (b.survivalProbability * b.immediateGain) - (a.survivalProbability * a.immediateGain)
          || b.baseValue - a.baseValue;
      }
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
    let recommendedPairKey = [...selectedPairs.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    if (!recommendedPairKey && onClock && opponentPicks === 0 && candidates.length) {
      const leadId = candidates[0].player.id;
      recommendedPairKey = pairValues
        .filter((pair) => pair.players.some((player) => player.id === leadId))
        .sort((a, b) => b.value - a.value)[0]?.players.map((player) => player.id).sort().join("|");
    }
    const recommendedPair = recommendedPairKey
      ? recommendedPairKey.split("|").map((id) => data.players.find((player) => player.id === id)).filter(Boolean)
      : [];
    const result = { candidates, byId: new Map(candidates.map((candidate) => [candidate.player.id, candidate])), currentPick, decisionPick, nextTurn, prefixPicks, opponentPicks, onClock, draftComplete, metrics, pointRanks, posterior, recommendedPair };
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
      market: (a, b) => marketRankFor(a, recommendations.metrics) - marketRankFor(b, recommendations.metrics),
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
    const market = marketFor(player);
    const injury = [player.injury?.gameStatus, player.injury?.practiceStatus, player.injury?.bodyPart].filter(Boolean).join(" · ");
    const injuryRisk = player.injuryRisk || {};
    const injuryRiskMarkup = `
      <div class="forecast-range injury-range">
        <div><span>Expected missed</span><strong>${Number(injuryRisk.expectedMissedGames || 0).toFixed(1)} games</strong></div>
        <div><span>Weekly onset</span><strong>${(100 * Number(injuryRisk.weeklyHazard || 0)).toFixed(1)}%</strong></div>
        <div><span>Prior injury record</span><strong>${Number(injuryRisk.historyEpisodes || 0)} episodes · ${Number(injuryRisk.historyMissedGames || 0)} missed</strong></div>
        <div><span>Size risk factor</span><strong>${Number(injuryRisk.sizeMultiplier || 1).toFixed(2)}×</strong></div>
      </div>`;
    const rangeMarkup = range.source === "historical rookie analogs" ? `
      <div class="forecast-range">
        <div><span>Rookie floor P10</span><strong>${range.p10.toFixed(1)}</strong></div>
        <div><span>Median P50</span><strong>${range.p50.toFixed(1)}</strong></div>
        <div><span>Upside P90</span><strong>${range.p90.toFixed(1)}</strong></div>
        <div><span>Effective analogs</span><strong>${range.effectiveSample.toFixed(0)}</strong></div>
      </div>` : "";
    const expertPoints = market?.espnHalfPprPoints == null ? NaN : Number(market.espnHalfPprPoints);
    const expertMarkup = Number.isFinite(expertPoints) ? `
      <div class="forecast-range">
        <div><span>Our half-PPR</span><strong>${Number(player.projectedPoints).toFixed(1)}</strong></div>
        <div><span>ESPN half-PPR est.</span><strong>${expertPoints.toFixed(1)}</strong></div>
        <div><span>Model difference</span><strong>${(Number(player.projectedPoints) - expertPoints >= 0 ? "+" : "")}${(Number(player.projectedPoints) - expertPoints).toFixed(1)}</strong></div>
        <div><span>ESPN ADP</span><strong>${market.adp == null ? "-" : Number(market.adp).toFixed(1)}</strong></div>
      </div>` : "";
    return `
      <div class="player-detail">
        <div class="season-components">
          <span class="detail-label">Projected season components</span>
          <div class="stat-grid">${statItems(player)}</div>
          ${expertMarkup}
          ${rangeMarkup}
          ${injuryRiskMarkup}
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
    const market = marketFor(player);
    const displayedDraftValue = state.sort === "actual_draft" && hindsight ? hindsight.value : recommendation?.survivalProbability;
    const projectedPoints = pointsFor(player);
    const range = scaledRange(player);
    const rookieMeta = range.source === "historical rookie analogs" ? ` · rookie P10–P90 ${range.p10.toFixed(0)}–${range.p90.toFixed(0)}` : "";
    const injuryMeta = player.injury?.gameStatus ? ` · ${escapeHtml(player.injury.gameStatus)}` : "";
    const marketMeta = !data.hasActuals && market?.adp ? ` · ESPN ADP ${Number(market.adp).toFixed(1)}` : "";
    const actionsDisabled = status !== "available" || recommendations.draftComplete;
    return `
      <tr class="player-row${rowClass}" data-id="${escapeHtml(player.id)}">
        <td class="rank-cell">
          <div class="rank-pair">
            <span><strong>${liveRank}</strong><small>Live</small></span>
            <span class="actual-rank"><strong>${data.hasActuals ? hindsight?.rank || "-" : market?.adp?.toFixed(1) || "-"}</strong><small>${data.hasActuals ? "Hindsight" : "ESPN ADP"}</small></span>
          </div>
        </td>
        <td class="rank-cell">
          <div class="rank-pair points-rank-pair">
            <span><strong>${recommendations.pointRanks.get(player.id)}</strong><small>Model</small></span>
            <span class="actual-rank actual-points-rank"><strong>${data.hasActuals ? player.actualRank : "-"}</strong><small>Actual</small></span>
          </div>
        </td>
        <td>
          <div class="player-cell">
            <img src="${teamLogo(player.team)}" alt="" onerror="this.hidden=true">
            <span><strong>${escapeHtml(player.name)}</strong><small>${player.projectedGames} projected games${player.depthRank ? ` · depth ${player.position}${player.depthRank}` : ""}${marketMeta}${rookieMeta}${injuryMeta}</small></span>
          </div>
        </td>
        <td><span class="${positionClass(player.position)}">${escapeHtml(player.position)}</span></td>
        <td class="team-cell">${escapeHtml(player.team)}</td>
        <td class="number-cell projection"><strong>${projectedPoints.toFixed(1)}</strong></td>
        <td class="number-cell actual-total actual-column">${data.hasActuals ? player.actualPoints.toFixed(1) : "-"}</td>
        <td class="number-cell">${(projectedPoints / player.projectedGames).toFixed(2)}</td>
        <td class="number-cell draft-value" title="Expected managed weekly lineup points added to your current roster">${recommendation ? `${recommendation.immediateGain >= 0 ? "+" : ""}${recommendation.immediateGain.toFixed(1)}` : "-"}</td>
        <td class="number-cell draft-value" title="${state.sort === "actual_draft" ? "Hindsight value over the format-derived replacement player" : `Estimated probability of remaining available to pick #${recommendations.onClock ? recommendations.nextTurn : recommendations.decisionPick}`}">${state.sort === "actual_draft" ? `${displayedDraftValue > 0 ? "+" : ""}${displayedDraftValue.toFixed(1)}` : recommendation ? `${Math.round(displayedDraftValue * 100)}%` : "-"}</td>
        <td>${statusMarkup(player, status)}</td>
        <td class="actions-cell">
          <div class="row-actions">
            <button type="button" data-action="mine" data-id="${escapeHtml(player.id)}" ${actionsDisabled ? "disabled" : ""} title="Add to my roster" aria-label="Add ${escapeHtml(player.name)} to my roster"><i data-lucide="user-plus"></i><span>Mine</span></button>
            <button type="button" data-action="other" data-id="${escapeHtml(player.id)}" ${actionsDisabled ? "disabled" : ""} title="Mark drafted by someone else" aria-label="Mark ${escapeHtml(player.name)} drafted by someone else"><i data-lucide="user-x"></i><span>Taken</span></button>
            <button type="button" data-action="expand" data-id="${escapeHtml(player.id)}" title="View game-by-game projections" aria-label="View ${escapeHtml(player.name)} game-by-game projections" aria-expanded="${expanded}"><i data-lucide="${expanded ? "chevron-up" : "chevron-down"}"></i></button>
          </div>
        </td>
      </tr>
      ${expanded ? `
        <tr class="detail-row">
          <td colspan="12">${playerDetail(player)}</td>
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
    const filledBase = ["QB", "RB", "WR", "TE", "K"].reduce(
      (total, position) => total + Math.min(counts[position] || 0, slots[position]), 0,
    );
    const benchUsed = Math.max(0, mine.length - filledBase - flexFilled);
    const benchSlots = Number(defaultConfig.benchSlots || 4);
    base.push(`<span class="need-chip${benchUsed < benchSlots ? " open" : " filled"}">Bench ${benchUsed}/${benchSlots}</span>`);
    return base.join("");
  }

  function renderSummary(recommendations) {
    const best = recommendations.candidates[0]?.player;
    const bestRecommendation = best ? recommendations.byId.get(best.id) : null;
    $("bestHeading").textContent = recommendations.draftComplete ? "Draft complete" : recommendations.onClock ? "Pick now" : `Target for pick #${recommendations.decisionPick}`;
    $("bestName").textContent = recommendations.draftComplete ? "Roster locked" : best?.name || "No player available";
    const pairNames = recommendations.recommendedPair.map((player) => player.name).join(" + ");
    $("bestMeta").textContent = pairNames
      ? `${recommendations.onClock ? "Recommended turn pair" : "Most frequent turn pair"} · ${pairNames}`
      : best ? `${best.position} · ${best.team} · ${scoringName()}` : "-";
    $("bestPoints").textContent = recommendations.draftComplete ? "-" : bestRecommendation ? `${Math.round(bestRecommendation.survivalProbability * 100)}%` : "-";
    $("bestMetricLabel").textContent = recommendations.onClock ? "Return survival" : "Survival to my pick";
    $("bestMetricUnit").textContent = `256 ESPN-market simulations to #${recommendations.onClock ? recommendations.nextTurn : recommendations.decisionPick}`;
    $("availableCount").textContent = data.players.filter((player) => statusFor(player.id) === "available").length;
    $("mineCount").textContent = data.players.filter((player) => statusFor(player.id) === "mine").length;
    $("takenCount").textContent = data.players.filter((player) => statusFor(player.id) === "other").length;
    const round = Math.floor((recommendations.currentPick - 1) / state.teams) + 1;
    $("clockPick").textContent = recommendations.draftComplete ? "Final" : `${round}.${String(((recommendations.currentPick - 1) % state.teams) + 1).padStart(2, "0")}`;
    $("clockMeta").textContent = recommendations.draftComplete ? `${state.picks.length} picks recorded` : recommendations.onClock ? "You are on the clock" : `Team ${snakeTeam(recommendations.currentPick)} selecting`;
    $("nextTurn").textContent = recommendations.draftComplete ? "-" : `#${recommendations.onClock ? recommendations.nextTurn : recommendations.decisionPick}`;
    $("nextTurnMeta").textContent = recommendations.draftComplete ? "Draft finished" : recommendations.onClock ? `${recommendations.opponentPicks} opponent picks away` : `${recommendations.decisionPick - recommendations.currentPick} picks until your turn`;
    $("rosterNeeds").innerHTML = rosterNeeds();
    $("undoButton").disabled = state.picks.length === 0;
    const orderedPosterior = Object.entries(recommendations.posterior).sort((a, b) => b[1] - a[1]);
    const fullPosterior = orderedPosterior.map(([name, probability]) => `${roomModels[name].label} ${Math.round(probability * 100)}%`).join(" · ");
    const fixedModel = { balanced: "balanced", rb_rush: "rb_heavy", wr_rush: "wr_heavy", early_qb: "early_qb", zero_rb: "zero_rb" }[state.scenario];
    $("roomPosteriorLabel").textContent = fixedModel
      ? `Fixed: ${roomModels[fixedModel].label}`
      : `Posterior: ${orderedPosterior.slice(0, 2).map(([name, probability]) => `${roomModels[name].label} ${Math.round(probability * 100)}%`).join(" · ")}`;
    $("roomPosteriorLabel").title = fullPosterior;
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
      setPlayerStatus(id, action);
    });
    $("undoButton").addEventListener("click", () => {
      const undone = state.picks.pop();
      savePicks();
      render();
      const player = data.players.find((item) => item.id === undone?.id);
      $("announcement").textContent = `${player?.name || "Last pick"} restored to available.`;
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
      ? `${data.scope}. Models refit through ${data.trainingThrough}; active rosters, starter depth, schedule, and game lines as of ${new Date(data.dataAsOf).toLocaleString()}. Player value comes from our forecasts; ESPN ADP is used only for opponent availability. Recommendations simulate managed weekly lineups, injury paths, eight bench slots, opponent choices, and your next snake turn.`
      : `${data.scope}. Recommendations combine game-level forecasts, format-derived replacement value, your roster, and the projected pool at your next snake turn; this remains a ${data.projectionSeason} out-of-sample validation board, not a live ${new Date().getFullYear()} preseason ranking.`;
    $("footerScope").textContent = `${data.projectionSeason} · ${scoringName()} · ${data.players.length} fantasy-relevant players`;
    $("injuryStatus").textContent = data.injuryReportsAvailable
      ? `Current injury report: ${data.injurySource}`
      : "Current injury designations unavailable · missing means unknown";
    const generated = new Date(data.generatedAt);
    $("updatedLabel").textContent = `Generated ${generated.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
    if (!data.hasActuals) {
      document.body.classList.add("no-actuals");
      $("draftRankSub").textContent = "Live · ESPN ADP";
      $("pointsRankSub").textContent = "Model";
      $("sortSelect").querySelectorAll('option[value="actual"], option[value="actual_draft"]').forEach((option) => { option.hidden = true; option.disabled = true; });
    }
    bindEvents();
    render();
    $("app").hidden = false;
  }

  window.addEventListener("DOMContentLoaded", boot);
})();
