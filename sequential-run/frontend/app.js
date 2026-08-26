const API_BASE_URL = "http://localhost:8000";

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (err) {
    throw new Error(`Не удалось подключиться к серверу API по адресу ${API_BASE_URL}.`);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {}
    throw new Error(`Ошибка API (${response.status}): ${detail}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function setError(el, message) {
  if (!message) {
    el.hidden = true;
    el.textContent = "";
  } else {
    el.hidden = false;
    el.textContent = message;
  }
}

async function loadMeals(date) {
  const tbody = document.getElementById("meals-tbody");
  const tableError = document.getElementById("table-error");
  setError(tableError, null);
  try {
    const meals = await apiRequest(`/meals?date=${date}`);
    tbody.innerHTML = "";
    const totals = { weight_g: 0, calories: 0, protein: 0, fat: 0, carbs: 0 };
    for (const m of meals) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${m.product}</td><td>${m.weight_g}</td><td>${m.calories}</td><td>${m.protein}</td><td>${m.fat}</td><td>${m.carbs}</td>`;
      tbody.appendChild(tr);
      totals.weight_g += m.weight_g;
      totals.calories += m.calories;
      totals.protein += m.protein;
      totals.fat += m.fat;
      totals.carbs += m.carbs;
    }
    document.getElementById("t-weight").textContent = totals.weight_g;
    document.getElementById("t-calories").textContent = totals.calories;
    document.getElementById("t-protein").textContent = totals.protein.toFixed(1);
    document.getElementById("t-fat").textContent = totals.fat.toFixed(1);
    document.getElementById("t-carbs").textContent = totals.carbs.toFixed(1);
  } catch (err) {
    setError(tableError, err.message);
  }
}

function init() {
  const tableDate = document.getElementById("table-date");
  const formDate = document.getElementById("f-date");
  tableDate.value = todayISO();
  formDate.value = todayISO();

  document.getElementById("refresh-btn").addEventListener("click", () => {
    loadMeals(tableDate.value);
  });

  document.getElementById("meal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const formError = document.getElementById("form-error");
    setError(formError, null);
    const payload = {
      product: document.getElementById("f-product").value,
      weight_g: parseFloat(document.getElementById("f-weight").value),
      date: document.getElementById("f-date").value,
      calories: parseFloat(document.getElementById("f-calories").value),
      protein: parseFloat(document.getElementById("f-protein").value),
      fat: parseFloat(document.getElementById("f-fat").value),
      carbs: parseFloat(document.getElementById("f-carbs").value),
    };
    try {
      await apiRequest("/meals", { method: "POST", body: JSON.stringify(payload) });
      e.target.reset();
      formDate.value = todayISO();
      if (tableDate.value === payload.date) {
        loadMeals(tableDate.value);
      }
    } catch (err) {
      setError(formError, err.message);
    }
  });

  loadMeals(tableDate.value);
}

document.addEventListener("DOMContentLoaded", init);
