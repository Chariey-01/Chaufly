/* iFinder public tracking page.
 *
 * Opened by the customer's emergency contact from the link in the safety SMS.
 * That reader is anxious and not technical: the page has to answer "where are
 * they and are they okay?" in one glance, with no interaction.
 *
 * Backed by GET /api/trips/{id}/public, which is deliberately narrow — first
 * names, masked plate, no coordinates, no phone numbers.
 */
(function () {
  "use strict";

  const API = "/api";
  const POLL_MS = 15000;

  const $ = (id) => document.getElementById(id);

  /* Trip id comes from the path: /track/TRP-884210 */
  function tripIdFromPath() {
    const parts = window.location.pathname.split("/").filter(Boolean);
    return parts.length ? decodeURIComponent(parts[parts.length - 1]) : "";
  }

  const tripId = tripIdFromPath();

  /* Copy that a worried relative can act on, not status codes. */
  const HEADLINES = {
    DRIVER_EN_ROUTE: {
      title: (d) =>
        d.driver_first_name
          ? d.driver_first_name + " is on the way to collect the car"
          : "A driver is on the way",
      sub: (d) =>
        d.driver_eta_minutes
          ? "Arriving in about " + d.driver_eta_minutes + " minutes."
          : "The driver is heading to the pickup point."
    },
    IN_PROGRESS: {
      title: () => "The trip is underway",
      sub: (d) => "Driving to " + d.destination + "."
    },
    COMPLETED: {
      title: () => "Trip completed safely",
      sub: (d) => "The car was delivered to " + d.destination + "."
    },
    CANCELLED: {
      title: () => "Trip was cancelled",
      sub: () => "This trip did not go ahead."
    },
    SOS: {
      title: () => "Emergency alert raised",
      sub: (d) =>
        "An SOS was triggered on this trip. The iFinder control room has been sent " +
        "the driver's details and the vehicle's last known location."
    }
  };

  const EVENT_LABELS = {
    TRIP_CREATED: "Trip booked",
    SAFETY_SMS_DISPATCHED: "Safety SMS sent to emergency contact",
    SOS_TRIGGERED: "Emergency SOS raised",
    TRIP_COMPLETED: "Trip completed",
    TRIP_STARTED: "Ride started",
    TRIP_CANCELLED: "Trip cancelled",
    PAYMENT_CALLBACK: "Payment processed",
    DRIVER_ARRIVED: "Driver arrived"
  };

  let failures = 0;
  let timer = null;

  function esc(s) {
    const map = { "&": "&#38;", "<": "&#60;", ">": "&#62;", '"': "&#34;", "'": "&#" + "39;" };
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) => map[c]);
  }

  function clock(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }

  function fullTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return (
      d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) +
      " " +
      d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    );
  }

  function setState(name) {
    ["loading", "missing", "error", "content"].forEach((s) => {
      $(s).classList.toggle("hidden", s !== name);
    });
  }

  function render(data) {
    setState("content");

    $("t-id").textContent = data.trip_id;

    const pill = $("t-status");
    pill.textContent = String(data.status).replace(/_/g, " ");
    pill.className = "pill-status pill-" + data.status;

    const copy = HEADLINES[data.status] || {
      title: () => "Trip in progress",
      sub: () => ""
    };
    $("headline").textContent = copy.title(data);
    $("subline").textContent = copy.sub(data);

    $("emergency-banner").classList.toggle("hidden", !data.is_emergency);

    $("k-passenger").textContent = data.customer_first_name || "—";
    $("k-driver").textContent = data.driver_first_name
      ? data.driver_first_name +
        (data.driver_rating ? " · ★ " + Number(data.driver_rating).toFixed(2) : "") +
        (data.driver_certified_manual ? " · manual & auto" : "")
      : "Not yet assigned";
    $("k-vehicle").textContent = data.vehicle || "—";
    $("k-destination").textContent = data.destination || "—";
    $("k-started").textContent = fullTime(data.started_at);
    $("k-arrived").textContent = fullTime(data.completed_at);

    const events = data.events || [];
    const ul = $("timeline");
    if (!events.length) {
      ul.innerHTML = '<li><span class="timeline-label muted">Waiting for updates…</span></li>';
    } else {
      ul.innerHTML = events
        .map((e) => {
          const alert = e.event_type === "SOS_TRIGGERED";
          const label = EVENT_LABELS[e.event_type] || e.event_type.replace(/_/g, " ");
          return (
            '<li class="' + (alert ? "is-alert" : "") + '">' +
            '<div class="timeline-label">' + esc(label) + "</div>" +
            '<div class="timeline-time">' + esc(clock(e.created_at)) + "</div>" +
            "</li>"
          );
        })
        .join("");
    }

    $("refreshed").textContent =
      "Updated " +
      new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

    // Nothing more will change once the trip is closed out.
    if (data.status === "COMPLETED" || data.status === "CANCELLED") {
      stop();
      $("refreshed").textContent = "Final";
    }
  }

  async function fetchStatus() {
    if (!tripId) {
      setState("missing");
      return;
    }

    try {
      const res = await fetch(API + "/trips/" + encodeURIComponent(tripId) + "/public", {
        headers: { Accept: "application/json" }
      });

      if (res.status === 404) {
        stop();
        setState("missing");
        return;
      }
      if (!res.ok) throw new Error("HTTP " + res.status);

      const data = await res.json();
      failures = 0;
      render(data);
    } catch (err) {
      failures += 1;
      // One blip shouldn't wipe a page someone is anxiously watching.
      if (failures >= 2) {
        stop();
        $("error-msg").textContent =
          "We couldn't reach iFinder. Check your connection, then try again.";
        setState("error");
      }
    }
  }

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  function start() {
    stop();
    fetchStatus();
    timer = setInterval(fetchStatus, POLL_MS);
  }

  /* Don't poll a page nobody is looking at — it wastes the phone's battery at
     exactly the moment the relative may need it. */
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else start();
  });

  $("btn-retry").addEventListener("click", () => {
    failures = 0;
    setState("loading");
    start();
  });

  start();
})();
