"use strict";

const EXAMPLE_VESSEL = {
  vessel_type: "bulk_carrier",
  gross_tonnage: 30000,
  vessel_age: 3,
  flag_tier: "tier_1",
  iacs_class: "yes",
  trading_area: "worldwide",
  deductible: 150000,
  claims_count_5yr: 0,
  agreed_hull_value: 28000000,
};

// Words that plain capitalising would get wrong.
const LABEL_OVERRIDES = { ro_ro: "Ro-ro" };

const WAKING = "This can take several seconds if the app has been idle.";

const form = document.getElementById("quote-form");
const fieldsBox = document.getElementById("fields");
const submitButton = document.getElementById("submit");
const statusLine = document.getElementById("form-status");
const formError = document.getElementById("form-error");
const resultBox = document.getElementById("result");

let currency = "";
let inputs = {};

const setText = (id, text) => {
  document.getElementById(id).textContent = text;
};

// "bulk_carrier" becomes "Bulk carrier".
function readable(value) {
  if (value in LABEL_OVERRIDES) return LABEL_OVERRIDES[value];
  const words = String(value).replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Inserts thousands separators into the string, so the value is never rounded by a float.
function withSeparators(text) {
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(String(text));
  if (!match) return String(text);
  const [, sign, whole, fraction = ""] = match;
  return sign + whole.replace(/\B(?=(\d{3})+$)/g, ",") + fraction;
}

const money = (text) => `${currency} ${withSeparators(text)}`;

function addField(name, definition) {
  const wrapper = document.createElement("div");
  wrapper.dataset.field = name;

  const label = document.createElement("label");
  label.htmlFor = name;
  label.textContent = definition.label;
  wrapper.append(label);

  let control;
  if (definition.type === "choice") {
    control = document.createElement("select");
    for (const option of definition.options) {
      control.add(new Option(readable(option), option));
    }
  } else {
    control = document.createElement("input");
    control.type = "number";
    control.min = definition.min;
    control.max = definition.max;
    control.step = definition.type === "integer" ? "1" : "any";
    const hint = document.createElement("p");
    hint.id = `${name}-hint`;
    hint.className = "hint";
    hint.textContent = `${withSeparators(definition.min)} to ${withSeparators(definition.max)}`;
    control.setAttribute("aria-describedby", hint.id);
    wrapper.append(hint);
  }
  control.id = name;
  control.name = name;
  control.required = true;
  if (name in EXAMPLE_VESSEL) control.value = EXAMPLE_VESSEL[name];
  label.after(control);
  fieldsBox.append(wrapper);
}

function clearErrors() {
  formError.hidden = true;
  formError.textContent = "";
  for (const line of form.querySelectorAll(".field-error")) {
    const control = form.elements[line.dataset.for];
    control.removeAttribute("aria-invalid");
    const hint = control.parentElement.querySelector(".hint");
    if (hint) control.setAttribute("aria-describedby", hint.id);
    else control.removeAttribute("aria-describedby");
    line.remove();
  }
}

// The API names fields in its messages, for example "less than agreed_hull_value".
function withFieldLabels(message) {
  let text = message;
  for (const [name, definition] of Object.entries(inputs)) {
    text = text.replaceAll(name, definition.label.toLowerCase());
  }
  return text;
}

function showGeneralError(message) {
  const line = document.createElement("div");
  line.textContent = message;
  formError.append(line);
  formError.hidden = false;
}

function showErrors(errors) {
  let firstInvalid = null;
  for (const { field, message } of errors) {
    const control = form.elements[field];
    if (!control) {
      showGeneralError(message);
      continue;
    }
    const line = document.createElement("p");
    line.id = `${field}-error`;
    line.className = "field-error";
    line.dataset.for = field;
    line.textContent = withFieldLabels(message);
    control.parentElement.append(line);
    control.setAttribute("aria-invalid", "true");
    const described = control.getAttribute("aria-describedby");
    control.setAttribute("aria-describedby", described ? `${described} ${line.id}` : line.id);
    firstInvalid ??= control;
  }
  firstInvalid?.focus();
}

function requestBody() {
  const body = {};
  for (const [name, definition] of Object.entries(inputs)) {
    const value = form.elements[name].value;
    body[name] = definition.type === "choice" ? value : Number(value);
  }
  return body;
}

function showResult(quote) {
  currency = quote.currency;
  setText("premium", money(quote.technical_premium));

  const rows = quote.factors.map((factor) => {
    const row = document.createElement("tr");
    const isChoice = inputs[factor.input]?.type === "choice";
    const cells = [
      ["Factor", factor.label, ""],
      ["Value", isChoice ? readable(factor.value) : withSeparators(factor.value), ""],
      ["Multiplier", factor.factor, "num"],
      ["Effect", withSeparators(factor.effect), "num"],
      ["Premium after", withSeparators(factor.premium_after), "num"],
    ];
    for (const [heading, text, className] of cells) {
      const cell = document.createElement("td");
      cell.textContent = text;
      cell.className = className;
      cell.dataset.label = heading;
      row.append(cell);
    }
    return row;
  });
  document.getElementById("factor-rows").replaceChildren(...rows);

  setText("base-premium", money(quote.base_premium));
  setText("rate-tonne", `${money(quote.rate_per_gross_tonne)} per ${quote.exposure_unit}`);
  setText("rate-value", `${quote.rate_on_hull_value_pct}%`);
  setText("model-version", quote.model_version);
  setText("git-commit", quote.git_commit);
  setText("quote-id", quote.quote_id);

  resultBox.hidden = false;
  resultBox.focus();
}

async function submitQuote(event) {
  event.preventDefault();
  clearErrors();
  submitButton.disabled = true;
  submitButton.textContent = "Getting quote…";
  statusLine.textContent = `Getting your quote. ${WAKING}`;
  statusLine.hidden = false;

  try {
    const response = await fetch("quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody()),
    });
    const data = await response.json().catch(() => null);

    if (response.ok && data) {
      showResult(data);
    } else if (Array.isArray(data?.errors)) {
      resultBox.hidden = true;
      showErrors(data.errors);
    } else {
      resultBox.hidden = true;
      showGeneralError(`The server returned an error (${response.status}). Please try again.`);
    }
  } catch {
    resultBox.hidden = true;
    showGeneralError("Could not reach the server. Check your connection and try again.");
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Get quote";
    statusLine.hidden = true;
  }
}

async function loadOptions() {
  try {
    const response = await fetch("options");
    if (!response.ok) throw new Error(String(response.status));
    const options = await response.json();
    currency = options.currency;
    inputs = options.inputs;
    for (const [name, definition] of Object.entries(inputs)) addField(name, definition);
    form.hidden = false;
    statusLine.hidden = true;
  } catch {
    statusLine.hidden = true;
    showGeneralError("Could not load the form. Reload the page to try again.");
  }
}

form.addEventListener("submit", submitQuote);
loadOptions();
