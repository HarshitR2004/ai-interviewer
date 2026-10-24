const form = document.querySelector("#preparation-form");
const fields = document.querySelector("#form-fields");
const feedback = document.querySelector("#feedback");
const actions = document.querySelector("#completed-actions");
const submit = document.querySelector("#submit-button");
let candidateId = null;
let busy = false;

function show(message, detail = "", error = false) {
  feedback.hidden = false;
  feedback.classList.toggle("error", error);
  document.querySelector("#feedback-title").textContent = message;
  document.querySelector("#feedback-detail").textContent = detail;
}

async function responseData(response) {
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Preparation could not continue. Please try again.",
    );
  }
  return response.json();
}

async function watch() {
  let failures = 0;
  for (;;) {
    let status;
    try {
      status = await responseData(
        await fetch(`/api/candidates/${candidateId}/status`),
      );
      failures = 0;
    } catch (error) {
      if (++failures >= 3)
        throw new Error(
          "Progress could not be checked. Refresh the page to reconnect.",
        );
      await new Promise((resolve) => setTimeout(resolve, 2500));
      continue;
    }
    show(status.message, status.warnings.join(" "), status.state === "failed");
    if (status.state === "failed") {
      localStorage.removeItem("interview-preparation");
      break;
    }
    if (status.state === "completed") {
      actions.hidden = false;
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

async function run(operation) {
  if (busy) return;
  busy = true;
  fields.disabled = true;
  form.setAttribute("aria-busy", "true");
  actions.hidden = true;
  show("Preparing your interview.");
  try {
    if (operation) {
      const result = await operation();
      candidateId = result.candidate_id;
      localStorage.setItem("interview-preparation", candidateId);
    }
    await watch();
  } catch (error) {
    show(
      error.message || "Preparation could not continue. Please try again.",
      "",
      true,
    );
    feedback.focus();
  } finally {
    busy = false;
    fields.disabled = false;
    form.removeAttribute("aria-busy");
    submit.hidden = !actions.hidden;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const file = document.querySelector("#resume").files[0];
  if (file && file.size > 10 * 1024 * 1024) {
    show("Please upload a PDF smaller than 10 MB.", "", true);
    feedback.focus();
    return;
  }
  run(async () =>
    responseData(
      await fetch("/api/candidates", { method: "POST", body: data }),
    ),
  );
});

document.querySelector("#update-button").addEventListener("click", () => {
  if (!document.querySelector("#job_description").reportValidity()) return;
  const body = {
    job_description: document.querySelector("#job_description").value,
    duration: Number(document.querySelector("#duration").value),
    seniority: document.querySelector("#seniority").value,
    interview_type: document.querySelector("#interview_type").value,
  };
  run(async () =>
    responseData(
      await fetch(`/api/candidates/${candidateId}/interview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    ),
  );
});

document.querySelector("#new-button").addEventListener("click", () => {
  candidateId = null;
  localStorage.removeItem("interview-preparation");
  actions.hidden = true;
  feedback.hidden = true;
  submit.hidden = false;
  form.reset();
  document.querySelector("#resume").focus();
});

const saved = localStorage.getItem("interview-preparation");
if (saved && /^[a-f0-9]{32}$/.test(saved)) {
  candidateId = saved;
  run();
}
