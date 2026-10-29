/* iFinder customer booking app.
 *
 * Vanilla JS on purpose: no build step, no node_modules, no bundler to break
 * five minutes before a demo. Everything here maps 1:1 onto a REST call, so the
 * whole customer journey is auditable by reading this file top to bottom.
 *
 * State lives in memory and mirrors into sessionStorage, so a mid-trip refresh
 * (someone's phone reclaims the tab) puts them back on the right screen.
 */
(function () {
  "use strict";

  const API = "/api";
  const STORE_KEY = "ifinder.state.v1";

  /* Westlands, Nairobi. Used as the pickup origin when the browser refuses
     geolocation — the match endpoint needs coordinates, not an address string. */
  const FALLBACK_LAT = -1.2642;
  const FALLBACK_LNG = 36.8045;

  /* ------------------------------------------------------------------ state */
  const state = {
    screen: "plan",
    pickup: { address: "Alchemist, Westlands", lat: null, lng: null },
    dropoff: { address: "Karen, Hardy", lat: null, lng: null },
    distanceKm: 8.5,
    transmission: "AUTOMATIC",
    quote: null,
    driver: null,
    trip: null, // { trip_id, status, driver: {name, phone, eta_minutes}, at_sms_dispatch }
    completion: null,
    rating: 0,
    tags: [],
    lastEvents: []
  };

  function saveState() {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(state));
    } catch (e) {
      /* private mode / quota — not worth surfacing */
    }
  }

  function loadState() {
    try {
      const raw = sessionStorage.getItem(STORE_KEY);
      if (!raw) return;
      Object.assign(state, JSON.parse(raw));
    } catch (e) {
      /* corrupt blob; start clean */
    }
  }

  function clearState() {
    try {
      sessionStorage.removeItem(STORE_KEY);
    } catch (e) {}
  }

  /* -------------------------------------------------------------------- dom */
  const $ = (id) => document.getElementById(id);
  const el = (sel, root) => (root || document).querySelector(sel);

  /* -------------------------------------------------------------------- fmt */
  function kes(n) {
    if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
    return Number(n).toLocaleString("en-KE", {
      minimumFractionDigits: 0,
      maximumFractionDigits: n % 1 === 0 ? 0 : 2
    });
  }

  function clock(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }

  function humanEventType(t) {
    return String(t || "")
      .replace(/_/g, " ")
      .toLowerCase()
      .replace(/^\w/, (c) => c.toUpperCase());
  }

  const ALERT_EVENTS = ["SOS_TRIGGERED", "PAYMENT_CALLBACK_FAILED", "TRIP_CANCELLED"];

  /* --------------------------------------------------------------- transport */
  async function api(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    if (opts.body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }

    let res;
    try {
      res = await fetch(API + path, opts);
    } catch (err) {
      throw new Error("Network error — check your connection and try again.");
    }

    let data = null;
    const text = await res.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (e) {
        data = null;
      }
    }

    if (!res.ok) {
      throw new Error(extractError(data, res.status));
    }
    return data;
  }

  /* FastAPI returns detail as a string for our 400/404/409 paths, but as a
     list of {loc,msg} dicts for validation failures. Both need to read well. */
  function extractError(data, status) {
    if (data && typeof data.detail === "string") return data.detail;
    if (data && Array.isArray(data.detail) && data.detail.length) {
      return data.detail
        .map((d) => {
          const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
          return field ? field + ": " + d.msg : d.msg;
        })
        .join("; ");
    }
    if (status === 404) return "Not found.";
    if (status === 409) return "That action isn't allowed right now.";
    return "Something went wrong (" + status + ").";
  }

  /* ----------------------------------------------------------------- toast */
  let toastTimer = null;

  function toast(title, msg, spinning) {
    $("toast-title").textContent = title;
    $("toast-msg").textContent = msg || "";
    $("toast-spin").classList.toggle("hidden", !spinning);
    $("toast-sheet").classList.add("open");
    clearTimeout(toastTimer);
    if (!spinning) {
      toastTimer = setTimeout(() => $("toast-sheet").classList.remove("open"), 3600);
    }
  }

  function toastHide() {
    clearTimeout(toastTimer);
    $("toast-sheet").classList.remove("open");
  }

  /* ---------------------------------------------------------------- screens */
  const SCREENS = ["plan", "quote", "trip", "pay", "rate", "done"];
  const STEP_OF = { plan: 1, quote: 2, trip: 3, pay: 4, rate: 4, done: 4 };

  function show(screen) {
    state.screen = screen;
    SCREENS.forEach((s) => {
      const node = $("screen-" + s);
      if (node) node.classList.toggle("hidden", s !== screen);
    });

    const step = STEP_OF[screen] || 1;
    document.querySelectorAll(".stepper-dot").forEach((dot) => {
      const n = Number(dot.dataset.step);
      dot.classList.toggle("done", n < step);
      dot.classList.toggle("now", n === step);
    });

    // SOS is only meaningful while a trip is live.
    const live = screen === "trip" && state.trip;
    $("sos-dock").classList.toggle("hidden", !live);
    $("btn-sos").classList.toggle("armed", !!live);

    window.scrollTo({ top: 0, behavior: "smooth" });
    saveState();
  }

  /* ------------------------------------------------------------ geolocation */
  function locate() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
        () => resolve(null),
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 }
      );
    });
  }

  /* ------------------------------------------------------------- screen: plan */
  function readPlan() {
    const t = el('input[name="transmission"]:checked');
    state.transmission = t ? t.value : "AUTOMATIC";

    state.pickup.address = $("pickup").value.trim() || "Pickup";
    state.dropoff.address = $("dropoff").value.trim() || "Destination";

    const dist = parseFloat($("distance").value);
    state.distanceKm = Number.isFinite(dist) && dist > 0 ? dist : 8.5;

    return {
      plate: ($("plate").value || "").trim().toUpperCase() || "KDA 123A",
      model: ($("carmodel").value || "").trim() || "Toyota Axio"
    };
  }

  function validatePlan() {
    if (!$("pickup").value.trim()) return "Enter a pickup point.";
    if (!$("dropoff").value.trim()) return "Enter a destination.";
    const d = parseFloat($("distance").value);
    if (!Number.isFinite(d) || d <= 0) return "Distance must be greater than zero.";
    if (d > 2000) return "That distance is too large.";
    if (!$("plate").value.trim()) return "Enter your number plate.";
    return null;
  }

  async function quoteAndMatch() {
    const problem = validatePlan();
    if (problem) {
      toast("Check your details", problem, false);
      return;
    }

    const car = readPlan();
    state.car = car;

    $("btn-quote").disabled = true;
    toast("Getting your fare", "Pricing the trip and finding a qualified driver…", true);

    try {
      /* Coordinates: try the browser, fall back to central Nairobi. The match
         endpoint requires numbers, and a real deployment would geocode the
         typed address here instead. */
      if (state.pickup.lat === null) {
        const pos = await locate();
        state.pickup.lat = pos ? pos.lat : FALLBACK_LAT;
        state.pickup.lng = pos ? pos.lng : FALLBACK_LNG;
        $("geo-hint").textContent = pos
          ? "Location found — using your GPS position."
          : "Location unavailable — using central Nairobi. Drivers near you may be missed.";
      }

      const quote = await api("/quote", {
        method: "POST",
        body: {
          pickup: { address: state.pickup.address, lat: state.pickup.lat, lng: state.pickup.lng },
          dropoff: { address: state.dropoff.address },
          distance_km: state.distanceKm,
          car_transmission: state.transmission
        }
      });
      state.quote = quote;

      let match = null;
      let matchError = null;
      try {
        match = await api("/drivers/match", {
          method: "POST",
          body: {
            car_transmission: state.transmission,
            pickup_lat: state.pickup.lat,
            pickup_lng: state.pickup.lng,
            radius_km: 5.0
          }
        });
        state.driver = match.matched_driver;
      } catch (e) {
        matchError = e.message;
        state.driver = null;
      }

      renderQuote(quote, state.driver, matchError);
      toastHide();
      show("quote");
    } catch (err) {
      toastHide();
      toast("Couldn't get a quote", err.message, false);
    } finally {
      $("btn-quote").disabled = false;
    }
  }

  function renderQuote(quote, driver, matchError) {
    $("q-fare").textContent = kes(quote.estimated_fare);
    $("q-distance").textContent = quote.distance_km + " km";
    $("q-duration").textContent = "~" + quote.estimated_duration_min + " min";

    $("q-breakdown").innerHTML =
      row("Base fare", kes(quote.base_fare) + " " + quote.currency) +
      row("Per km × " + quote.distance_km, kes(quote.per_km_rate)) +
      row("Total", kes(quote.estimated_fare) + " " + quote.currency);

    $("q-expiry").textContent =
      "Quote valid for " + Math.round(quote.quote_expires_in_sec / 60) + " minutes.";

    const card = $("driver-card");
    if (!driver) {
      card.classList.remove("hidden");
      $("d-avatar").textContent = "!";
      $("d-name").textContent = "No driver available";
      $("d-rating").textContent = "";
      $("d-trips").textContent = "";
      $("d-dci").classList.add("hidden");
      $("d-cert").classList.add("hidden");
      $("d-eta").textContent = "—";
      $("d-dist").textContent = "—";
      $("d-ntsa").textContent = "—";
      $("btn-start").disabled = true;
      toast("No driver nearby", matchError || "Try again in a moment.", false);
      return;
    }

    card.classList.remove("hidden");
    $("btn-start").disabled = false;

    const initials = driver.full_name
      .split(" ")
      .map((p) => p[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();
    $("d-avatar").textContent = initials;
    $("d-name").textContent = driver.full_name;
    $("d-rating").textContent = "★ " + Number(driver.rating).toFixed(2);
    $("d-trips").textContent = driver.total_trips + " trips";

    const q = driver.qualifications || {};
    $("d-dci").classList.remove("hidden");
    $("d-dci").textContent = q.dci_good_conduct_verified ? "DCI vetted" : "DCI check pending";
    $("d-dci").className =
      "badge " + (q.dci_good_conduct_verified ? "badge-ok" : "badge-warn");

    $("d-cert").classList.remove("hidden");
    $("d-cert").textContent =
      driver.transmission_certified === "MANUAL_AND_AUTO" ? "Manual & auto" : "Automatic only";

    $("d-eta").textContent = driver.eta_minutes + " min";
    $("d-dist").textContent = Number(driver.current_distance_km).toFixed(2) + " km";
    $("d-ntsa").textContent = q.ntsa_license_no || "—";

    if (driver.photo_url) {
      const img = $("d-photo");
      img.src = driver.photo_url;
      img.classList.remove("hidden");
      $("d-avatar").textContent = "";
      $("d-avatar").appendChild(img);
    }

    // Surface the transmission trap before they commit, not after.
    if (state.transmission === "MANUAL" && driver.transmission_certified === "AUTO_ONLY") {
      toast("Transmission mismatch", "That driver can't drive a manual car.", false);
      $("btn-start").disabled = true;
    }
  }

  function row(k, v) {
    return (
      '<div class="kv"><dt>' + escapeHtml(k) + "</dt><dd>" + escapeHtml(v) + "</dd></div>"
    );
  }

  /* Build the replacement from character codes so no literal entity text sits
     in this file — it survives copy/paste and editor round-trips intact. */
  const HTML_ESCAPES = {
    "&": "&#38;",
    "<": "&#60;",
    ">": "&#62;",
    '"': "&#34;",
    "'": "&#" + "39;"
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
  }

  /* ------------------------------------------------------------- start trip */
  function validateStart() {
    if (!state.driver) return "Pick a driver first.";
    if (!$("me-name").value.trim()) return "Enter your name.";
    if (!$("me-phone").value.trim()) return "Enter your M-Pesa number.";
    if (!$("ec-name").value.trim()) return "Enter your safety contact's name.";
    if (!$("ec-phone").value.trim()) return "Enter your safety contact's phone.";
    return null;
  }

  async function startTrip() {
    const problem = validateStart();
    if (problem) {
      toast("Missing details", problem, false);
      return;
    }

    $("btn-start").disabled = true;
    toast("Starting your trip", "Telling your safety contact…", true);

    const car = state.car || readPlan();

    try {
      const res = await api("/trips/start", {
        method: "POST",
        body: {
          user_name: $("me-name").value.trim(),
          user_phone: $("me-phone").value.trim(),
          car_details: {
            make_model: car.model,
            registration_plate: car.plate,
            transmission: state.transmission
          },
          driver_id: state.driver.driver_id,
          pickup_address: state.pickup.address,
          dropoff_address: state.dropoff.address,
          pickup_lat: state.pickup.lat,
          pickup_lng: state.pickup.lng,
          distance_km: state.distanceKm,
          emergency_contact: {
            name: $("ec-name").value.trim(),
            phone: $("ec-phone").value.trim()
          }
        }
      });

      state.trip = res;
      renderTrip();
      toastHide();
      show("trip");
      startPolling();
    } catch (err) {
      toastHide();
      toast("Couldn't start trip", err.message, false);
    } finally {
      $("btn-start").disabled = false;
    }
  }

  /* ------------------------------------------------------------ live trip UI */
  function renderTrip() {
    const t = state.trip;
    if (!t) return;

    $("t-id").textContent = t.trip_id;
    const pill = $("t-status");
    pill.textContent = String(t.status || "").replace(/_/g, " ");
    pill.className = "pill-status pill-" + (t.status || "DRIVER_EN_ROUTE");

    const name = (t.driver && t.driver.name) || "Your driver";
    $("t-driver").textContent = name;
    $("t-avatar").textContent = name
      .split(" ")
      .map((p) => p[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();
    $("t-eta").textContent =
      t.status === "DRIVER_EN_ROUTE"
        ? "Arriving in ~" + ((t.driver && t.driver.eta_minutes) || 6) + " min"
        : "On the way to " + state.dropoff.address;

    $("t-pickup").textContent = state.pickup.address;
    $("t-dropoff").textContent = state.dropoff.address;

    const sms = t.at_sms_dispatch || {};
    if (sms.sent) {
      $("t-sms").textContent = "Sent to " + sms.recipient;
      $("t-sms").className = "";
    } else {
      $("t-sms").textContent = sms.error ? "Failed — " + sms.error : "Not configured";
      $("t-sms").className = "muted";
    }

    const url = window.location.origin + "/track/" + t.trip_id;
    $("t-track-url").textContent = url;
    $("btn-copy").onclick = () => copyText(url);

    // Buttons track the real state machine rather than being blindly enabled.
    const arrived = $("btn-arrived");
    const finish = $("btn-finish");
    if (t.status === "DRIVER_EN_ROUTE") {
      arrived.classList.remove("hidden");
      arrived.disabled = false;
      finish.classList.add("hidden");
    } else if (t.status === "IN_PROGRESS") {
      arrived.classList.add("hidden");
      finish.classList.remove("hidden");
      finish.disabled = false;
    } else {
      arrived.classList.add("hidden");
      finish.classList.add("hidden");
    }

    renderEvents(state.lastEvents);
  }

  function renderEvents(events) {
    const ul = $("t-events");
    if (!events || !events.length) {
      ul.innerHTML = '<li><span class="timeline-label muted">Waiting for the first update…</span></li>';
      return;
    }
    ul.innerHTML = events
      .map((e) => {
        const isAlert = e.event_type === "SOS_TRIGGERED" || e.event_type === "PAYMENT_FAILED";
        return (
          '<li class="' + (isAlert ? "is-alert" : "") + '">' +
          '<div class="timeline-label">' + escapeHtml(humanEventType(e.event_type)) + "</div>" +
          '<div class="timeline-time">' + escapeHtml(clock(e.created_at)) + "</div>" +
          "</li>"
        );
      })
      .join("");
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        () => toast("Copied", "Tracking link copied to clipboard.", false),
        () => toast("Copy failed", "Long-press the link to copy it.", false)
      );
    } else {
      toast("Copy manually", text, false);
    }
  }

  /* Polling: cheap and honest. A websocket is the right answer later, but for
     an MVP this is one GET every 6s against a local SQLite read. */
  let pollTimer = null;
  let pollFailures = 0;

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(refreshTrip, 6000);
    refreshTrip();
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  async function refreshTrip() {
    if (!state.trip) return;
    try {
      const detail = await api("/trips/" + state.trip.trip_id);
      pollFailures = 0;
      state.lastEvents = detail.events || [];
      if (detail.status && detail.status !== state.trip.status) {
        state.trip.status = detail.status;
      }
      if (state.screen === "trip") renderTrip();
      saveState();
    } catch (e) {
      // Three consecutive misses and the network is genuinely down, not blipping.
      if (++pollFailures >= 3 && state.screen === "trip") {
        $("t-sms").textContent = "Connection lost — retrying";
        $("t-sms").className = "muted";
      }
    }
  }

  /* ------------------------------------------------------------ begin ride */
  async function beginRide() {
    const btn = $("btn-arrived");
    btn.disabled = true;
    toast("Starting the ride", "Marking the trip as underway…", true);
    try {
      const res = await api("/trips/" + state.trip.trip_id + "/start", { method: "POST" });
      state.trip.status = res.status || "IN_PROGRESS";
      renderTrip();
      toastHide();
      toast("Ride started", "Have a safe trip.", false);
    } catch (err) {
      toastHide();
      toast("Couldn't start ride", err.message, false);
      btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------- complete */
  async function finishTrip() {
    const btn = $("btn-finish");
    btn.disabled = true;
    toast("Closing the trip", "Calculating your final fare…", true);

    try {
      const res = await api("/trips/" + state.trip.trip_id + "/complete", {
        method: "POST",
        body: { distance_km: state.distanceKm, payment_method: "MPESA_STK_PUSH" }
      });
      state.completion = res;
      stopPolling();
      renderPay(res);
      toastHide();
      show("pay");
    } catch (err) {
      toastHide();
      toast("Couldn't close trip", err.message, false);
      btn.disabled = false;
    }
  }

  function renderPay(res) {
    $("p-fare").textContent = kes(res.final_fare);
    $("p-fare-btn").textContent = kes(res.final_fare) + " " + res.currency;
    $("p-trip").textContent = res.trip_id;
    $("p-duration").textContent = res.duration_minutes + " min";
    setPayStatus(res.payment_status);
    $("p-receipt-card").classList.add("hidden");
    $("btn-to-rate").classList.add("hidden");
    $("btn-mpesa").disabled = false;
    $("btn-cash").disabled = false;
  }

  function setPayStatus(status) {
    const map = {
      PENDING: ["Awaiting payment", "badge-warn"],
      REQUESTED: ["Prompt sent — check your phone", "badge-info"],
      PAID: ["Paid", "badge-ok"],
      FAILED: ["Payment failed", "badge-bad"],
      CASH: ["Paid cash", "badge-ok"]
    };
    const entry = map[status] || [status, "badge-info"];
    $("p-status").textContent = entry[0];
    $("p-status").className = "badge " + entry[1];
  }

  /* ---------------------------------------------------------------- pay */
  async function payMpesa() {
    const res = state.completion;
    if (!res) return;

    const checkoutId = res.mpesa_checkout_request_id;
    if (!checkoutId) {
      // M-Pesa rejected the request outright — fall back honestly.
      toast("M-Pesa unavailable", res.mpesa_error || "Use cash instead.", false);
      setPayStatus("FAILED");
      return;
    }

    $("btn-mpesa").disabled = true;
    $("btn-cash").disabled = true;
    setPayStatus("REQUESTED");
    toast("Prompt sent", "Enter your M-Pesa PIN on your phone.", true);

    /* Against a real Daraja sandbox, Safaricom calls /api/mpesa/callback itself.
       With the simulator on (the default for local dev) nothing would ever call
       back, so we post the identical payload ourselves after a short pause. */
    if (checkoutId.indexOf("SIMULATED") !== -1) {
      await sleep(1400);
      try {
        await api("/mpesa/callback", {
          method: "POST",
          body: {
            Body: {
              stkCallback: {
                MerchantRequestID: "sim-merchant",
                CheckoutRequestID: checkoutId,
                ResultCode: 0,
                ResultDesc: "The service request is processed successfully.",
                CallbackMetadata: {
                  Item: [
                    { Name: "Amount", Value: res.final_fare },
                    { Name: "MpesaReceiptNumber", Value: "SIM" + randomRef() },
                    { Name: "PhoneNumber", Value: $("me-phone").value.trim() }
                  ]
                }
              }
            }
          }
        });
      } catch (e) {
        toast("Callback failed", e.message, false);
      }
    }

    await pollPayment();
  }

  async function payCash() {
    $("btn-mpesa").disabled = true;
    $("btn-cash").disabled = true;
    toast("Cash payment", "Recording cash settlement…", true);
    try {
      await api("/trips/" + state.trip.trip_id + "/pay/cash", { method: "POST" });
      await pollPayment(true);
    } catch (err) {
      toast("Couldn't record cash", err.message, false);
      $("btn-cash").disabled = false;
    }
  }

  async function pollPayment(forceCash) {
    const deadline = Date.now() + 25000;
    let last = null;

    while (Date.now() < deadline) {
      try {
        const detail = await api("/trips/" + state.trip.trip_id);
        last = detail;
        if (detail.payment_status === "PAID" || detail.payment_status === "CASH") break;
        if (detail.payment_status === "FAILED") break;
      } catch (e) {
        /* keep polling; transient */
      }
      await sleep(1500);
    }

    toastHide();

    const status = last ? last.payment_status : forceCash ? "CASH" : "PENDING";
    state.completion.payment_status = status;
    setPayStatus(status);
    saveState();

    $("p-receipt-card").classList.remove("hidden");
    $("p-r-status").textContent =
      status === "PAID" ? "Payment confirmed" : status === "CASH" ? "Cash recorded" : "Not confirmed";
    $("p-receipt").textContent =
      (last && last.mpesa_receipt) || (status === "CASH" ? "CASH" : "—");

    if (status === "PAID" || status === "CASH") {
      const paidFare = last && last.final_fare ? last.final_fare : state.completion.final_fare;
      $("p-fare").textContent = kes(paidFare);
      $("btn-to-rate").classList.remove("hidden");
      toast("Payment received", "Asante! Please rate your driver.", false);
    } else {
      $("btn-mpesa").disabled = false;
      $("btn-cash").disabled = false;
      toast("Payment pending", "No confirmation yet. Try again or pay cash.", false);
    }
  }

  function randomRef() {
    return Math.random().toString(36).slice(2, 8).toUpperCase();
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  /* ---------------------------------------------------------------- rating */
  function paintStars() {
    document.querySelectorAll(".star").forEach((b) => {
      const on = Number(b.dataset.v) <= state.rating;
      b.classList.toggle("on", on);
      b.setAttribute("aria-checked", String(Number(b.dataset.v) === state.rating));
    });
    $("btn-submit-rating").disabled = state.rating === 0;
  }

  function toggleTag(tag, node) {
    const i = state.tags.indexOf(tag);
    if (i === -1) state.tags.push(tag);
    else state.tags.splice(i, 1);
    node.classList.toggle("on", state.tags.indexOf(tag) !== -1);
  }

  async function submitRating() {
    if (!state.rating) return;
    $("btn-submit-rating").disabled = true;
    toast("Saving rating", "Updating your driver's score…", true);

    try {
      const res = await api("/trips/" + state.trip.trip_id + "/rate", {
        method: "POST",
        body: {
          rating: state.rating,
          tags: state.tags,
          feedback_comment: $("r-comment").value.trim() || null
        }
      });
      toastHide();
      state.newRating = res.new_driver_average_rating;
      renderDone();
      show("done");
    } catch (err) {
      toastHide();
      $("btn-submit-rating").disabled = false;
      toast("Couldn't save rating", err.message, false);
    }
  }

  function renderDone() {
    const c = state.completion || {};
    const parts = [];
    if (typeof state.newRating === "number") {
      parts.push(
        "Your " + state.rating + "-star rating moved " +
          ((state.driver && state.driver.full_name) || "the driver") +
          "'s average to ★ " + state.newRating.toFixed(2) + "."
      );
    } else {
      parts.push("Thanks for driving safely with iFinder.");
    }
    $("done-msg").textContent = parts.join(" ");

    $("done-summary").innerHTML =
      row("Trip", c.trip_id || (state.trip && state.trip.trip_id) || "—") +
      row("Driver", (state.driver && state.driver.full_name) || "—") +
      row("Route", (state.pickup.address || "") + " → " + (state.dropoff.address || "")) +
      row("Fare", kes(c.final_fare) + " " + (c.currency || "KES")) +
      row("Payment", c.payment_status || "—");
  }

  /* ------------------------------------------------------------------- SOS */
  async function sendSos() {
    if (!state.trip) return;
    $("btn-sos-confirm").disabled = true;
    $("sos-sheet").classList.remove("open");

    const coords = await locate();
    const lat = coords ? coords.lat : state.pickup.lat || FALLBACK_LAT;
    const lng = coords ? coords.lng : state.pickup.lng || FALLBACK_LNG;

    toast("Sending SOS", "Alerting your contact and our control room…", true);

    try {
      const res = await api("/trips/" + state.trip.trip_id + "/sos", {
        method: "POST",
        body: {
          current_lat: lat,
          current_lng: lng,
          trigger_reason: "PASSENGER_TRIGGERED_SOS"
        }
      });

      toastHide();
      state.trip.status = "SOS";
      renderTrip();

      $("sos-done-sub").textContent =
        res.status === "EMERGENCY_BROADCAST_SENT"
          ? "Our control room and your safety contact have been alerted."
          : "We recorded the alert but the SMS may not have gone out. Call us now.";

      const recipients = (res.sms_dispatched_to || []).join(", ");
      $("sos-done-details").innerHTML =
        row("Case number", res.incident_ticket_id) +
        row("Alerted", recipients || "—") +
        row("Voice call queued", res.at_voice_alert_queued ? "Yes" : "No") +
        row("Location sent", lat.toFixed(4) + ", " + lng.toFixed(4));

      $("sos-done-sheet").classList.add("open");
    } catch (err) {
      toastHide();
      $("sos-done-sub").textContent =
        "We couldn't send the alert. Call emergency services directly.";
      $("sos-done-details").innerHTML =
        '<div class="kv"><dt>Error</dt><dd>' + escapeHtml(err.message) + "</dd></div>";
      $("sos-done-sheet").classList.add("open");
    } finally {
      $("btn-sos-confirm").disabled = false;
    }
  }

  /* --------------------------------------------------------------- restart */
  function resetTrip() {
    stopPolling();
    clearState();
    state.screen = "plan";
    state.quote = null;
    state.driver = null;
    state.trip = null;
    state.completion = null;
    state.rating = 0;
    state.tags = [];
    state.lastEvents = [];
    state.newRating = null;
    state.pickup.lat = null;
    state.pickup.lng = null;
    document.querySelectorAll(".star").forEach((b) => b.classList.remove("on"));
    document.querySelectorAll(".chip").forEach((b) => b.classList.remove("on"));
    $("r-comment").value = "";
    paintStars();
    show("plan");
  }

  /* ------------------------------------------------------------------ wire */
  function wire() {
    $("btn-geo").addEventListener("click", async () => {
      $("btn-geo").disabled = true;
      $("geo-hint").textContent = "Finding you…";
      const pos = await locate();
      $("btn-geo").disabled = false;
      if (pos) {
        state.pickup.lat = pos.lat;
        state.pickup.lng = pos.lng;
        $("geo-hint").textContent =
          "Location found (" + pos.lat.toFixed(4) + ", " + pos.lng.toFixed(4) + ").";
      } else {
        $("geo-hint").textContent =
          "Location unavailable — we'll use central Nairobi instead.";
      }
      saveState();
    });

    $("btn-quote").addEventListener("click", quoteAndMatch);
    $("btn-back-plan").addEventListener("click", () => show("plan"));
    $("btn-start").addEventListener("click", startTrip);
    $("btn-arrived").addEventListener("click", beginRide);
    $("btn-finish").addEventListener("click", finishTrip);
    $("btn-mpesa").addEventListener("click", payMpesa);
    $("btn-cash").addEventListener("click", payCash);
    $("btn-to-rate").addEventListener("click", () => show("rate"));
    $("btn-submit-rating").addEventListener("click", submitRating);
    $("btn-skip-rating").addEventListener("click", () => {
      renderDone();
      show("done");
    });
    $("btn-new-trip").addEventListener("click", resetTrip);

    document.querySelectorAll(".star").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.rating = Number(btn.dataset.v);
        paintStars();
        saveState();
      });
    });

    document.querySelectorAll(".chip").forEach((btn) => {
      btn.addEventListener("click", () => toggleTag(btn.dataset.tag, btn));
    });

    $("btn-sos").addEventListener("click", () => $("sos-sheet").classList.add("open"));
    $("btn-sos-cancel").addEventListener("click", () =>
      $("sos-sheet").classList.remove("open")
    );
    $("btn-sos-confirm").addEventListener("click", sendSos);
    $("btn-sos-close").addEventListener("click", () =>
      $("sos-done-sheet").classList.remove("open")
    );

    // Escape closes any open sheet — desktop nicety, phones use the buttons.
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        document.querySelectorAll(".sheet.open").forEach((s) => s.classList.remove("open"));
      }
    });
  }

  /* ------------------------------------------------------------------ boot */
  async function boot() {
    wire();
    paintStars();
    loadState();

    // Health check is quiet, but it turns a blank screen into an explanation.
    try {
      const health = await api("/health");
      $("topbar-meta").textContent =
        health.environment === "development" ? "Nairobi · demo" : "Nairobi";
    } catch (e) {
      toast("Backend unreachable", "Start the API with: uvicorn app.main:app", false);
    }

    if (state.screen === "trip" && state.trip) {
      renderTrip();
      show("trip");
      startPolling();
    } else if (state.screen === "pay" && state.completion) {
      renderPay(state.completion);
      show("pay");
    } else if (state.screen === "quote" && state.quote) {
      renderQuote(state.quote, state.driver, null);
      show("quote");
    } else {
      show("plan");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
