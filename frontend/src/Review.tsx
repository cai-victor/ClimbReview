import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Attempt, ClimbEvent, Coaching, CoachingCard, clock, DetectorCoverage, Feedback, Gap, Job, Limb, Movement, OverlaySample, percent, performanceApi, Placement, PlacementReview, Result, Summary } from "./api";
import { DigestPanel } from "./DigestPanel";
import { EventCard, eventTitle } from "./EventCard";
import { isUncertain, limbOf, MovementChart } from "./MovementChart";
import { BetaPanel, CoachingCardView, ComparePanel, cueHasFeet, cueHasHands, FootPlacements, GlancePanel, NextAttempt, ObservedRoutePanel, ReviewedLists } from "./Performance";
import { Focus, Mark, Player, PlayerHandle, Trail } from "./Player";
import { ClimbProfile } from "./Story";
import { scrollTo, TabItem, Tabs } from "./ui";

const CONTEXT_MS = 1000;
const REASONS: Record<string, string> = {
  no_pose: "no body was detected", non_finite: "the model returned no usable coordinate", out_of_frame: "the joint was outside the picture",
  visibility_missing: "the model gave no visibility value", low_visibility: "the joint was probably hidden or poorly seen",
  low_presence: "the model was unsure a joint was there", implausible_torso_scale: "the detected body shape was implausibly sized",
  camera_motion: "the camera appeared to move", repeated_source_frame: "the video repeated a frame, so no new movement was observed",
};

interface Track { key: string; label: string; events: ClimbEvent[]; detector: string }
type RowKey = "low" | Limb;
const ROWS: { key: RowKey; label: string; detector: string }[] = [
  { key: "left_foot", label: "Left foot", detector: "foot_motion_left" }, { key: "right_foot", label: "Right foot", detector: "foot_motion_right" },
  { key: "left_wrist", label: "Left wrist", detector: "wrist_motion_left" }, { key: "right_wrist", label: "Right wrist", detector: "wrist_motion_right" },
  { key: "low", label: "Low movement", detector: "low_movement" },
];
const FEET: RowKey[] = ["left_foot", "right_foot"], HANDS: RowKey[] = ["left_wrist", "right_wrist"], ALL: RowKey[] = ROWS.map((r) => r.key);
const rowOf = (event: ClimbEvent): RowKey => limbOf(event) ?? "low";

const LIMB_MAP: Record<string, Limb> = { left_foot: "left_foot", right_foot: "right_foot", left_wrist: "left_wrist", right_wrist: "right_wrist", left_hand: "left_wrist", right_hand: "right_wrist" };

type TabKey = "moments" | "next" | "route" | "compare" | "evidence";
type CueFilter = "all" | "feet" | "hands";
const typing = (target: EventTarget | null) => target instanceof HTMLElement && (target.isContentEditable || ["TEXTAREA", "SELECT"].includes(target.tagName)
  || (target instanceof HTMLInputElement && !["checkbox", "radio", "range", "button", "file"].includes(target.type)));
const stacked = () => window.matchMedia("(max-width: 1000px)").matches;

export function Review({ attempt, run, onReanalyze, onAttemptChanged }: { attempt: Attempt; run: Job; onReanalyze: () => void; onAttemptChanged: () => void }) {
  const [result, setResult] = useState<Result | null>(null);
  const [events, setEvents] = useState<ClimbEvent[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [samples, setSamples] = useState<OverlaySample[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");           // a failed save never replaces the review
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [looping, setLooping] = useState(false);
  const [skeleton, setSkeleton] = useState(true);
  const [time, setTime] = useState(0);
  const [gapInfo, setGapInfo] = useState<{ gap: Gap; detector: string } | null>(null);
  const [movement, setMovement] = useState<Movement>({ available: false });
  const [shown, setShown] = useState<RowKey[]>(ALL);
  const [hideUncertain, setHideUncertain] = useState(false);
  const [focus, setFocus] = useState<Focus>("all");
  const [coaching, setCoaching] = useState<Coaching | null>(null);
  const [cue, setCue] = useState<string | null>(null);
  const [placementMark, setPlacementMark] = useState<Placement | null>(null);
  const [betaKey, setBetaKey] = useState(0);
  const [tab, setTab] = useState<TabKey>("moments");
  const [tracksOpen, setTracksOpen] = useState<boolean | null>(null);
  const [cueFilter, setCueFilter] = useState<CueFilter>("all");
  const [allCards, setAllCards] = useState(false);
  const checkedMaps = useRef(new Set<string>());
  const player = useRef<PlayerHandle>(null);
  const stage = useRef<HTMLDivElement>(null);

  const loadCoaching = useCallback(async () => {
    const data = await performanceApi.coaching(run.id);
    const map = data.available ? data.hold_map : null;
    if (map && !map.alignment && !checkedMaps.current.has(map.id)) {
      // Whether marks line up with the video is measured for each analysis, not assumed.
      checkedMaps.current.add(map.id);
      await performanceApi.checkAlignment(run.id, map.id);
      setCoaching(await performanceApi.coaching(run.id));
      setBetaKey((key) => key + 1);
    } else setCoaching(data);
  }, [run.id]);
  useEffect(() => { loadCoaching().catch((e) => setNotice(e.message)); }, [loadCoaching]);

  useEffect(() => {
    Promise.all([api.getAnalysis(run.id), api.getEvents(run.id), api.getPoses(run.id), api.getMovement(run.id)])
      .then(([analysis, eventData, poses, series]) => {
        setResult(analysis.result ?? null); setEvents(eventData.events); setSummary(eventData.summary); setSamples(poses.samples); setMovement(series);
      }).catch((e) => setError(e.message));
  }, [run.id]);

  const bounds = result?.attempt_bounds_ms;
  const span = bounds ? bounds.end - bounds.start : 1;
  const percentOf = (ms: number) => bounds ? ((ms - bounds.start) / span) * 100 : 0;
  const cards = useMemo(() => (coaching?.available ? coaching.cards : []), [coaching]);
  const matches = useCallback((card: CoachingCard) => cueFilter === "all" || (cueFilter === "feet" ? cueHasFeet(card) : cueHasHands(card)), [cueFilter]);
  const byTime = useMemo(() => cards.filter(matches).sort((a, b) => a.start_ms - b.start_ms), [cards, matches]);
  const selectedEvent = events.find((e) => e.id === selected) ?? null;
  const selectedCue: CoachingCard | null = cards.find((c) => c.id === cue) ?? null;

  // A filter that hides the selection also clears it, with its loop, path, and marks.
  useEffect(() => {
    if (selectedEvent && (!shown.includes(rowOf(selectedEvent)) || (hideUncertain && isUncertain(selectedEvent)))) setSelected(null);
  }, [selectedEvent, shown, hideUncertain]);
  useEffect(() => { if (selectedCue && !matches(selectedCue)) setCue(null); }, [selectedCue, matches]);
  useEffect(() => { if (!selectedEvent && !selectedCue) setLooping(false); }, [selectedEvent, selectedCue]);

  const loopRange = useMemo(() => {
    const focusWindow = selectedEvent ?? selectedCue;
    if (!looping || !focusWindow || !bounds) return null;
    return { start: Math.max(bounds.start, focusWindow.start_ms - CONTEXT_MS), end: Math.min(bounds.end, focusWindow.end_ms + CONTEXT_MS) };
  }, [looping, selectedEvent, selectedCue, bounds]);

  const trails = useMemo<Trail[]>(() => {
    if (!movement.available) return [];
    const pathOf = (limb: Limb, start: number, end: number): Trail => {
      const data = movement.limbs[limb];
      const points = movement.t.flatMap((t, i) => (t >= start && t <= end && data.x[i] !== null ? [{ t, x: data.x[i]!, y: data.y[i]! }] : []));
      return { points, side: limb.startsWith("left") ? "left" : "right" };
    };
    const limb = selectedEvent && limbOf(selectedEvent);
    if (selectedEvent && limb) return [pathOf(limb, selectedEvent.start_ms, selectedEvent.end_ms)];
    if (selectedCue) return selectedCue.limbs.map((name) => pathOf(LIMB_MAP[name], selectedCue.start_ms, selectedCue.end_ms));
    return [];
  }, [selectedEvent, selectedCue, movement]);

  const marks = useMemo<Mark[]>(() => {
    if (placementMark) return [{ x: placementMark.x, y: placementMark.y, label: `${placementMark.anchor} point` }];
    return selectedCue?.alternatives.map((option) => ({ x: option.x, y: option.y, label: `try H${option.hold_index + 1}` })) ?? [];
  }, [selectedCue, placementMark]);

  const showTab = (next: TabKey) => { setTab(next); if (next === "evidence") setTracksOpen(true); };
  const afterRender = (action: () => void) => window.setTimeout(action, 60);

  const select = (event: ClimbEvent) => {
    setSelected(event.id); setGapInfo(null); setCue(null); setPlacementMark(null); showTab("evidence");
    if (bounds) player.current?.seek(Math.max(bounds.start, event.start_ms - CONTEXT_MS));
    afterRender(() => scrollTo(document.getElementById(`card-${event.id}`)));
  };

  /** Selecting a card and selecting its timeline marker are the same action: same selection, same lead-in. */
  const openCue = (id: string, options: { toggle?: boolean; play?: boolean } = {}) => {
    const card = cards.find((c) => c.id === id);
    if (!card || !bounds) return;
    if (options.toggle && cue === id) { setCue(null); return; }
    if (!matches(card)) setCueFilter("all");
    setCue(id); setSelected(null); setGapInfo(null); setPlacementMark(null); setTab("moments");
    player.current?.seek(Math.max(bounds.start, card.start_ms - CONTEXT_MS));
    if (options.play) { player.current?.play(); if (stacked()) scrollTo(stage.current, "start"); }
    else afterRender(() => scrollTo(document.getElementById(`cue-${id}`)));
  };
  const stepCue = (direction: 1 | -1) => {
    if (!byTime.length) return;
    const index = byTime.findIndex((c) => c.id === cue);
    const next = index < 0
      ? (direction === 1 ? byTime.find((c) => c.start_ms > time) ?? byTime[0] : [...byTime].reverse().find((c) => c.start_ms < time) ?? byTime[byTime.length - 1])
      : byTime[(index + direction + byTime.length) % byTime.length];
    openCue(next.id);
  };
  const saveFeedback = async (card: CoachingCard, next: Feedback) => {
    setSaving(true); setNotice("");
    try { await performanceApi.putDecision(run.id, card.id, next); await loadCoaching(); }
    catch (e) { setNotice(`Your choice was not saved: ${(e as Error).message} Choose it again to retry.`); }
    finally { setSaving(false); }
  };
  const seekPlacement = (item: Placement) => { setPlacementMark(item); setCue(null); setSelected(null); setFocus("feet"); player.current?.seek(item.review_ms); if (stacked()) scrollTo(stage.current, "start"); };
  const savePlacement = async (item: Placement, review: PlacementReview) => {
    setNotice("");
    try { await performanceApi.putPlacement(run.id, item.id, review); await loadCoaching(); }
    catch (e) { setNotice(`Your answer was not saved: ${(e as Error).message} Choose it again to retry.`); }
  };

  const hasSelection = Boolean(selectedEvent || selectedCue);
  const keys = useRef({ stepCue, hasSelection });
  keys.current = { stepCue, hasSelection };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (typing(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "o") setSkeleton((v) => !v);
      else if (key === "l" && keys.current.hasSelection) setLooping((v) => !v);
      else if (key === "n") keys.current.stepCue(1);
      else if (key === "p") keys.current.stepCue(-1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (error) return (
    <section className="card empty" data-testid="review-error"><strong>This analysis could not be loaded</strong><span role="alert">{error}</span>
      <div className="row tight" style={{ justifyContent: "center" }}><button className="button" onClick={() => window.location.reload()}>Reload</button><button className="button" onClick={onReanalyze}>Analyze again</button></div></section>
  );
  if (!result || !summary || !bounds) return <p className="muted" role="status">Loading the analysis…</p>;

  const coverage = result.coverage.detectors;
  const footAvailable = Boolean(summary.foot_analysis_available);
  const passes = (event: ClimbEvent) => shown.includes(rowOf(event)) && !(hideUncertain && isUncertain(event));
  const visibleEvents = events.filter(passes);
  const rows = ROWS.filter((row) => coverage[row.detector] && shown.includes(row.key));
  const tracks: Track[] = rows.map((row) => ({ key: row.key, label: row.label, detector: row.detector, events: visibleEvents.filter((e) => rowOf(e) === row.key) }));
  const toggle = (key: RowKey) => setShown((list) => list.includes(key) ? list.filter((k) => k !== key) : [...list, key]);
  const chartLimbs = shown.filter((key): key is Limb => key !== "low");
  const selectById = (id: string) => { const event = events.find((e) => e.id === id); if (event) { if (!passes(event)) { setShown(ALL); setHideUncertain(false); } select(event); } };
  const reasonText = (gap: Gap) => {
    const entries = Object.entries(gap.reasons ?? {});
    return entries.length ? entries.slice(0, 3).map(([key]) => REASONS[key] ?? key).join("; ") : "tracking was not continuous here";
  };
  const countOf = (value: number | null) => (value === null ? "unavailable" : String(value));
  const priority = summary.review_priority.event_ids.map((id) => events.find((e) => e.id === id)).filter(Boolean) as ClimbEvent[];
  const showTracks = tracksOpen ?? (coaching !== null && cards.length === 0);
  const top = coaching?.available ? coaching.top_card_ids : [];
  const ordered = [...top.map((id) => cards.find((c) => c.id === id)).filter(Boolean) as CoachingCard[], ...cards.filter((c) => !top.includes(c.id)).sort((a, b) => a.start_ms - b.start_ms)];
  const expanded = allCards || cueFilter !== "all" || (cue !== null && !top.includes(cue));
  const listed = (expanded ? ordered : ordered.filter((c) => top.includes(c.id))).filter(matches);
  const feetCount = cards.filter(cueHasFeet).length, handCount = cards.filter(cueHasHands).length;
  const chosen = coaching?.available ? coaching.plan?.chosen.length ?? 0 : 0;
  const tabs: TabItem<TabKey>[] = [
    { key: "moments", label: "Opportunities", count: coaching?.available ? cards.length : null }, { key: "next", label: "Next attempt", count: chosen || null },
    { key: "route", label: "Route" }, { key: "compare", label: "Compare" }, { key: "evidence", label: "Evidence" },
  ];
  const seekBar = (event: React.MouseEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const box = event.currentTarget.getBoundingClientRect();
    player.current?.seek(bounds.start + ((event.clientX - box.left) / box.width) * span);
  };

  const toolbar = (
    <>
      <button className="button small" aria-pressed={skeleton} data-testid="overlay-toggle" title="Show or hide everything drawn on the video (O)" onClick={() => setSkeleton((v) => !v)}>Overlay {skeleton ? "on" : "off"}</button>
      <label className="sr-only" htmlFor="overlay-focus">Body parts drawn</label>
      <select id="overlay-focus" data-testid="overlay-focus" value={focus} disabled={!skeleton} onChange={(e) => setFocus(e.target.value as Focus)}>
        <option value="all">Whole body</option><option value="feet">Legs and feet</option><option value="hands">Arms and hands</option>
      </select>
      <label className="check" title="Repeat the selected moment with 1 s before and after (L)"><input type="checkbox" checked={looping && hasSelection} disabled={!hasSelection} onChange={(e) => setLooping(e.target.checked)} /> Loop this moment</label>
    </>
  );

  return (
    <div className="review">
      <div className="review-main">
        <div ref={stage}>
          <Player ref={player} src={attempt.video_url!} samples={samples} showSkeleton={skeleton} onTime={setTime} loop={loopRange} focus={focus} trails={trails} marks={marks} toolbar={toolbar} emphasis={selectedCue?.limbs ?? []} highlight={selectedCue?.highlight ?? null}
            onLoopExit={() => setLooping(false)} holds={coaching?.available && coaching.hold_map?.usable ? coaching.hold_map.holds : []} />
        </div>
        <p className="keys">Left side is drawn orange, right side blue. Keys: <span className="kbd">O</span> overlay <span className="kbd">L</span> loop <span className="kbd">N</span> <span className="kbd">P</span> next and previous opportunity</p>

        <section className="card timeline-card" aria-label="Timeline">
          <div className="timeline-head">
            <h2>Timeline <span className="muted small-text num">{clock(bounds.start)} to {clock(bounds.end)}</span></h2>
            <span className="sep" />
            {byTime.length > 0 && (
        <div className="seg" role="group" aria-label="Step through opportunities">
          <button className="button small" data-testid="cue-prev" title="Previous opportunity (P)" onClick={() => stepCue(-1)}><span aria-hidden="true">‹</span> Previous</button>
          <button className="button small" data-testid="cue-next" title="Next opportunity (N)" onClick={() => stepCue(1)}>Next <span aria-hidden="true">›</span></button>
        </div>
      )}
            <button className="button small quiet" aria-expanded={showTracks} data-testid="toggle-tracks" onClick={() => setTracksOpen(!showTracks)}>{showTracks ? "Hide" : "Show"} limb tracks</button>
          </div>
          <div className="timeline">
            {cards.length > 0 && (
              <div className="cue-track">
                <div className="track-label">Opportunities</div>
                <div className="track-bar" onClick={seekBar}>
                  {byTime.map((card) => (
                    <button key={card.id} className="cue-mark" data-testid="timeline-cue" aria-pressed={cue === card.id} title={`${clock(card.start_ms)} ${card.title}`} aria-label={`Opportunity at ${clock(card.start_ms)}: ${card.title}`}
                      style={{ left: `${percentOf(card.start_ms)}%`, width: `${((card.end_ms - card.start_ms) / span) * 100}%` }} onClick={() => openCue(card.id)} />
                  ))}
                  <div className="playhead" style={{ left: `${Math.min(100, Math.max(0, percentOf(time)))}%` }} />
                </div>
              </div>
            )}
            {showTracks && tracks.map((track) => {
              const item: DetectorCoverage = coverage[track.detector];
              return (
                <div className="track" key={track.key}>
                  <div className="track-label">{track.label}</div>
                  <div className="track-bar">
                    {item.gaps.map((gap) => (
                      <button key={`g${gap.start_ms}`} className="gap" title={`Not analyzable ${clock(gap.start_ms)} to ${clock(gap.end_ms)}`}
                        aria-label={`${track.label}: could not be tracked ${clock(gap.start_ms)} to ${clock(gap.end_ms)}`}
                        style={{ left: `${percentOf(gap.start_ms)}%`, width: `${(gap.duration_ms / span) * 100}%` }}
                        onClick={() => { setGapInfo({ gap, detector: track.label }); setSelected(null); player.current?.seek(gap.start_ms); }} />
                    ))}
                    {track.events.map((event) => (
                      <button key={event.id} data-testid="timeline-event" className={`event-mark ${event.type} ${isUncertain(event) ? "uncertain" : ""} ${selected === event.id ? "selected" : ""}`}
                        title={eventTitle(event)} aria-label={`${eventTitle(event)} ${clock(event.start_ms)}`} aria-pressed={selected === event.id}
                        style={{ left: `${percentOf(event.start_ms)}%`, width: `${Math.max(0.6, ((event.end_ms - event.start_ms) / span) * 100)}%` }}
                        onClick={() => select(event)} />
                    ))}
                    <div className="playhead" style={{ left: `${Math.min(100, Math.max(0, percentOf(time)))}%` }} />
                    {item.status !== "available" && <span className="track-empty">Unavailable: not enough tracking</span>}
                  </div>
                </div>
              );
            })}
          </div>
          {showTracks && <p className="legend"><span className="swatch mark-swatch" style={{ marginLeft: 0 }} /> Movement <span className="swatch low-swatch" /> Low movement{footAvailable && <><span className="swatch uncertain-swatch" /> Uncertain foot tracking</>} <span className="swatch gap-swatch" /> Could not be tracked</p>}
          {gapInfo && (
            <p className="notice-text small-text" role="status" style={{ marginTop: 8 }}>
              {gapInfo.detector}: nothing could be measured from {clock(gapInfo.gap.start_ms)} to {clock(gapInfo.gap.end_ms)} because {reasonText(gapInfo.gap)}.
            </p>
          )}
        </section>
      </div>

      <div className="review-side">
        <Tabs items={tabs} active={tab} onChange={showTab} label="Review sections" />
        {notice && <div className="banner" role="alert"><span>{notice}</span><button className="button small" onClick={() => setNotice("")}>Dismiss</button></div>}

        {tab === "moments" && (
          <div className="tabpanel" role="tabpanel" id="panel-moments" aria-labelledby="tab-moments">
            {!footAvailable && (
              <section className="card notice" data-testid="old-run-notice" role="status">
                <strong>This older analysis has no footwork.</strong> It was made before left and right foot tracking was added. Its hand results and your notes are kept as they were.
                <div className="row tight"><button className="button primary" data-testid="reanalyze-feet" onClick={onReanalyze}>Reanalyze to add footwork</button><button className="button" onClick={() => showTab("evidence")}>See what was detected</button></div>
              </section>
            )}
            {!coaching && <p className="muted" role="status">Looking for moments to review…</p>}
            {coaching && !coaching.available && footAvailable && (
              <section className="card empty" data-testid="coaching-unavailable"><strong>No coaching suggestions for this analysis</strong>{coaching.reason}
                <div className="row tight" style={{ justifyContent: "center" }}><button className="button" onClick={() => showTab("evidence")}>See what was detected</button></div></section>
            )}
            {coaching && !coaching.available && !footAvailable && <p className="muted small-text" data-testid="coaching-unavailable">{coaching.reason}</p>}
            {coaching?.available && (
              <>
                {coaching.story?.available && <ClimbProfile story={coaching.story} bounds={bounds} time={time} onSeek={(ms) => player.current?.seek(ms)} />}
                {coaching.story && !coaching.story.available && <p className="muted small-text" data-testid="story-unavailable">No climb profile: {coaching.story.reason}</p>}
                <div className="panel-head">
                  <h2>Opportunities ({cards.length})</h2>
                  {cards.length > 0 && (
                    <div className="seg" role="group" aria-label="Show opportunities for">
                      <button className="button small" aria-pressed={cueFilter === "all"} data-testid="cue-filter-all" onClick={() => setCueFilter("all")}>All</button>
                      <button className="button small" aria-pressed={cueFilter === "feet"} data-testid="cue-filter-feet" disabled={feetCount === 0} onClick={() => { setCueFilter("feet"); setFocus("feet"); }}>Feet {feetCount}</button>
                      <button className="button small" aria-pressed={cueFilter === "hands"} data-testid="cue-filter-hands" disabled={handCount === 0} onClick={() => { setCueFilter("hands"); setFocus("hands"); }}>Hands {handCount}</button>
                    </div>
                  )}
                </div>
                {cards.length === 0 && (
                  <section className="card empty" data-testid="no-cards"><strong>Nothing stood out in this attempt</strong>No suggestion met its rules. That is not a verdict on the climb. You can still watch it with the overlay and see what was checked below.</section>
                )}
                {cards.length > 0 && !expanded && cards.length > listed.length && <p className="muted small-text">Start with these {listed.length}: the whole-attempt ones first, then one moment of each kind. Each is something to test, not a fault.</p>}
                {(coaching.cards_after_leaving_wall ?? 0) > 0 && <p className="muted small-text" data-testid="after-wall-note">{coaching.cards_after_leaving_wall} suggestion{coaching.cards_after_leaving_wall === 1 ? " was" : "s were"} left out because {coaching.cards_after_leaving_wall === 1 ? "it" : "they"} came before you started climbing or after you left the wall.</p>}
                {cards.length > 0 && listed.length === 0 && <p className="muted">No {cueFilter === "feet" ? "footwork" : "hand"} opportunities in this attempt.</p>}
                {listed.map((card) => (
                  <CoachingCardView key={card.id} card={card} selected={cue === card.id} busy={saving} onSelect={() => openCue(card.id, { toggle: true })} onWatch={() => openCue(card.id, { play: true })} onFeedback={(next) => void saveFeedback(card, next)} />
                ))}
                {cueFilter === "all" && cards.length > top.length && <button className="button small" data-testid="toggle-all-cards" onClick={() => setAllCards((v) => !v)}>{allCards ? "Show the main ones only" : `Show all ${cards.length} opportunities`}</button>}
                <details className="card" data-testid="foot-placements-section" open={cueFilter === "feet" || undefined}>
                  <summary data-testid="foot-placements-open">Foot placements to check ({coaching.placements.length})</summary>
                  <FootPlacements coaching={coaching} onSeek={seekPlacement} onSave={savePlacement} attemptId={attempt.id} />
                </details>
                <ReviewedLists coaching={coaching} />
              </>
            )}
          </div>
        )}

        {tab === "next" && (
          <div className="tabpanel" role="tabpanel" id="panel-next" aria-labelledby="tab-next">
            {coaching?.available && <NextAttempt coaching={coaching} onCue={(id) => openCue(id)} />}
            <ReflectionPanel attemptId={attempt.id} />
          </div>
        )}

        {tab === "route" && (
          <div className="tabpanel" role="tabpanel" id="panel-route" aria-labelledby="tab-route">
            {coaching?.available
              ? <BetaPanel attempt={attempt} runId={run.id} reloadKey={betaKey} onFeedback={() => { void loadCoaching(); }} />
              : <section className="card empty"><strong>Route tools need a current analysis</strong>Reanalyze this attempt to compare your movement with marked holds.<div className="row tight" style={{ justifyContent: "center" }}><button className="button" onClick={onReanalyze}>Reanalyze</button><a className="button" href={`#/holds/${attempt.id}`}>Mark route holds</a></div></section>}
            {coaching?.available && coaching.observed_route && <ObservedRoutePanel route={coaching.observed_route} onSeek={(ms) => player.current?.seek(ms)} />}
          </div>
        )}

        {tab === "compare" && (
          <div className="tabpanel" role="tabpanel" id="panel-compare" aria-labelledby="tab-compare">
            <ComparePanel attempt={attempt} onSaved={onAttemptChanged} />
          </div>
        )}

        {tab === "evidence" && (
          <div className="tabpanel" role="tabpanel" id="panel-evidence" aria-labelledby="tab-evidence">
            {coaching?.available && <GlancePanel glance={coaching.glance} onSeek={(ms) => player.current?.seek(ms)} />}
            {result.warnings.length > 0 && <section className="card notice"><h2>About this recording</h2><ul className="warnings">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul></section>}
            {footAvailable && (
              <section className="card filters" aria-label="Filters">
                <div className="row tight" style={{ margin: 0 }}>
                  <div className="seg" role="group" aria-label="Limbs shown">
                    <button className="button small" aria-pressed={shown.length === ALL.length} data-testid="filter-all" onClick={() => setShown(ALL)}>Everything</button>
                    <button className="button small" aria-pressed={shown.length === 2 && FEET.every((k) => shown.includes(k))} data-testid="filter-feet" onClick={() => { setShown(FEET); setFocus("feet"); }}>Feet only</button>
                    <button className="button small" aria-pressed={shown.length === 2 && HANDS.every((k) => shown.includes(k))} data-testid="filter-hands" onClick={() => { setShown(HANDS); setFocus("hands"); }}>Hands only</button>
                  </div>
                  {(shown.length !== ALL.length || hideUncertain) && <span className="chip accent" data-testid="filter-active">Filtered: {visibleEvents.length} of {events.length}</span>}
                </div>
                <details>
                  <summary>Choose limbs one by one</summary>
                  {ROWS.map((row) => <label className="choice" key={row.key}><input type="checkbox" data-testid={`filter-${row.key}`} checked={shown.includes(row.key)} onChange={() => toggle(row.key)} /> {row.label}</label>)}
                  <label className="choice"><input type="checkbox" data-testid="hide-uncertain" checked={hideUncertain} onChange={(e) => setHideUncertain(e.target.checked)} /> Hide uncertain foot episodes</label>
                </details>
              </section>
            )}
            {movement.available && chartLimbs.length > 0 && (
              <section className="card" aria-label="Movement chart">
                <h2>How fast each limb moved</h2>
                <MovementChart movement={movement} events={visibleEvents} limbs={chartLimbs} bounds={bounds} time={time} selected={selected} onSeek={(ms) => player.current?.seek(ms)} />
              </section>
            )}
            {!movement.available && <section className="card"><h2>How fast each limb moved</h2><p className="muted">This analysis has no movement chart. Reanalyze the attempt to add one.</p></section>}
            {summary.digest && <DigestPanel digest={summary.digest} onEvent={selectById} />}
            <section className="card">
              <h2>Summary</h2>
              <table className="facts"><tbody>
                <tr><th>Attempt duration</th><td>{clock(summary.attempt_duration_ms)}</td></tr>
                <tr><th>Time analyzable for low movement</th><td>{percent(summary.eligible.low_movement.fraction)}</td></tr>
                <tr><th>Time analyzable for left / right wrist</th><td>{percent(summary.eligible.wrist_motion_left.fraction)} / {percent(summary.eligible.wrist_motion_right.fraction)}</td></tr>
                {footAvailable && <tr><th>Time analyzable for left / right foot</th><td>{percent(summary.eligible.foot_motion_left.fraction)} / {percent(summary.eligible.foot_motion_right.fraction)}</td></tr>}
                <tr><th>Low movement, of analyzable time</th><td>{percent(summary.low_movement_fraction_of_eligible)}</td></tr>
                <tr><th>Left / right wrist episodes</th><td>{countOf(summary.wrist_episode_counts.left)} / {countOf(summary.wrist_episode_counts.right)}</td></tr>
                {footAvailable && <tr><th>Left / right foot episodes</th><td>{countOf(summary.foot_episode_counts!.left)} / {countOf(summary.foot_episode_counts!.right)}</td></tr>}
              </tbody></table>
              <p className="muted small-text">These describe what was visible. They are not a technique score, and fewer pauses or movements do not mean better climbing.</p>
              {priority.length > 0 && (<>
                <h3>Suggested order to rewatch</h3>
                <p className="muted small-text">{summary.review_priority.meaning}</p>
                <ol className="plain-list">{priority.filter(passes).map((event) => <li key={event.id}><button className="link" onClick={() => select(event)}>{clock(event.start_ms)}: {eventTitle(event)}</button></li>)}</ol>
              </>)}
            </section>
            <h2 style={{ margin: 0 }}>Detected movements ({visibleEvents.length}{visibleEvents.length !== events.length ? ` of ${events.length}` : ""})</h2>
            {events.length === 0 && <section className="card empty"><strong>No movements were detected</strong>Nothing met the rules in the parts of this attempt that could be tracked. Gaps are hatched on the timeline.</section>}
            {events.length > 0 && visibleEvents.length === 0 && <p className="muted">The current filter hides every movement. <button className="link" onClick={() => { setShown(ALL); setHideUncertain(false); }}>Show everything</button></p>}
            {visibleEvents.map((event) => (
              <EventCard key={event.id} event={event} runId={run.id} selected={selected === event.id} movement={movement} time={time} onSeek={(ms) => player.current?.seek(ms)}
                onSelect={() => select(event)} onSaved={(saved) => setEvents((list) => list.map((e) => (e.id === event.id ? { ...e, review: saved } : e)))} />
            ))}
            <section className="card">
              <h2>Downloads and details</h2>
              <div className="row tight">
                {(["html", "csv", "json"] as const).map((format) => (
                  <a key={format} className="button small" href={`/api/analyses/${run.id}/export?format=${format}`} download>{format === "html" ? "Report (HTML)" : format.toUpperCase()}</a>
                ))}
                <button className="button small" onClick={onReanalyze}>Change start and end, reanalyze</button>
              </div>
              <p className="muted small-text">Pipeline {result.pipeline_version} · {result.detection.detector_version} · configuration {result.config_hash.slice(0, 12)}. Thresholds are starting values that have not been validated against human labels.</p>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function ReflectionPanel({ attemptId }: { attemptId: string }) {
  const [value, setValue] = useState({ observation: "", next_focus: "" });
  const [status, setStatus] = useState("");
  const [loaded, setLoaded] = useState(false);     // typing waits for the saved text, so a late load never overwrites it
  useEffect(() => { api.getReflection(attemptId).then(setValue).catch(() => setStatus("Your saved notes could not be loaded. Saving now would replace them.")).finally(() => setLoaded(true)); }, [attemptId]);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true); setStatus("");
    try { setValue(await api.putReflection(attemptId, value)); setStatus("Saved."); }
    catch (e) { setStatus(`Not saved: ${(e as Error).message} Your text is still here; try again.`); }
    finally { setBusy(false); }
  };
  return (
    <section className="card">
      <h2>Your notes on this attempt</h2>
      <label>What did you notice?<textarea data-testid="reflection-observation" disabled={!loaded} value={value.observation} onChange={(e) => { setStatus(""); setValue({ ...value, observation: e.target.value }); }} /></label>
      <label>What will you focus on next time?<textarea data-testid="reflection-focus" disabled={!loaded} value={value.next_focus} onChange={(e) => { setStatus(""); setValue({ ...value, next_focus: e.target.value }); }} /></label>
      <button className="button primary" data-testid="save-reflection" disabled={busy || !loaded} onClick={save} style={{ marginTop: 8 }}>{busy ? "Saving…" : "Save notes"}</button>
      {status && <span className="muted" role="status"> {status}</span>}
    </section>
  );
}
