'use strict';

/**
 * Базовый URL backend API.
 * Если у backend будет другой порт/хост — поменять только эту строку.
 * Контракт, на который рассчитан этот файл, — РЕАЛЬНЫЙ, зафиксированный
 * в api/API_CONTRACT.md (поля product_name/weight_grams/consumed_at/
 * calories/proteins/fats/carbs, GET /meals?date=YYYY-MM-DD). Перевод между
 * этими "серверными" именами и "внутренними" именами формы/таблицы
 * (product/weight_g/date/calories/protein/fat/carbs) сделан в одном месте —
 * функциях mapMealToApi() / mapMealFromApi() ниже.
 */
const API_BASE_URL = 'http://localhost:8000';

const state = {
  meals: [],
  // Продукт, выбранный из справочника (GET /products) - пока он не сброшен,
  // изменение веса автоматически пересчитывает калории/БЖУ через
  // GET /products/portion. Ручное редактирование полей калорий/БЖУ или
  // текста продукта сбрасывает выбор (см. onNutritionFieldManualEdit /
  // onProductInput) - это единственная точка, где "источник истины" для
  // формы переключается между "из справочника" и "введено вручную".
  selectedProduct: null,
  suggestions: [],
  activeSuggestionIndex: -1,
};

const els = {};

document.addEventListener('DOMContentLoaded', init);

function init() {
  els.form = document.getElementById('meal-form');
  els.product = document.getElementById('field-product');
  els.productSuggestions = document.getElementById('product-suggestions');
  els.catalogHint = document.getElementById('product-catalog-hint');
  els.weight = document.getElementById('field-weight');
  els.mealDate = document.getElementById('field-date');
  els.calories = document.getElementById('field-calories');
  els.protein = document.getElementById('field-protein');
  els.fat = document.getElementById('field-fat');
  els.carbs = document.getElementById('field-carbs');
  els.formError = document.getElementById('form-error');
  els.submitBtn = document.getElementById('submit-btn');

  els.dayPicker = document.getElementById('day-picker');
  els.reloadBtn = document.getElementById('reload-btn');
  els.tableBody = document.getElementById('meals-tbody');
  els.summaryRow = document.getElementById('summary-row');
  els.statusBanner = document.getElementById('status-banner');
  els.apiBaseLabel = document.getElementById('api-base-label');

  els.apiBaseLabel.textContent = API_BASE_URL;

  const today = todayIso();
  els.mealDate.value = today;
  els.dayPicker.value = today;

  els.form.addEventListener('submit', onSubmit);
  els.dayPicker.addEventListener('change', () => loadMeals(els.dayPicker.value));
  els.reloadBtn.addEventListener('click', () => loadMeals(els.dayPicker.value));

  els.product.addEventListener('input', onProductInput);
  els.product.addEventListener('keydown', onProductKeydown);
  els.product.addEventListener('blur', () => {
    // Небольшая задержка: клик по подсказке тоже вызывает blur у поля ввода,
    // и без задержки список подсказок успел бы скрыться раньше, чем сработает
    // mousedown-обработчик выбора подсказки.
    setTimeout(hideSuggestions, 150);
  });
  els.weight.addEventListener('input', onWeightInput);
  for (const field of [els.calories, els.protein, els.fat, els.carbs]) {
    field.addEventListener('input', onNutritionFieldManualEdit);
  }

  // Рисуем пустую таблицу сразу, не дожидаясь сети — страница не должна
  // выглядеть сломанной, если backend недоступен (например, открыта как file://).
  renderTable();
  loadMeals(today);
}

/**
 * Простой debounce: откладывает вызов fn на delayMs после последнего
 * обращения, сбрасывая таймер при каждом новом вызове. Используется, чтобы
 * не бить по /products и /products/portion на каждое нажатие клавиши.
 */
function debounce(fn, delayMs) {
  let timer = null;
  return (...args) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

function todayIso() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/* ---------------------------------------------------------------------- */
/* API                                                                    */
/* ---------------------------------------------------------------------- */

class ApiError extends Error {}

async function apiRequest(path, options) {
  const url = `${API_BASE_URL}${path}`;
  let response;
  try {
    response = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch (networkErr) {
    // Сюда попадаем, если сервер не запущен, недоступен, или запрос
    // заблокирован CORS/mixed-content (например, страница открыта как file://).
    throw new ApiError(
      `Не удалось подключиться к серверу API по адресу ${API_BASE_URL}. ` +
        `Проверьте, что backend запущен и разрешает запросы с этой страницы. (${networkErr.message})`
    );
  }

  if (!response.ok) {
    let message = `Сервер вернул ошибку ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.detail) {
        message = formatErrorDetail(body.detail);
      }
    } catch (_) {
      /* тело ответа не JSON — игнорируем, оставляем сообщение по умолчанию */
    }
    throw new ApiError(message);
  }

  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch (_) {
    return null;
  }
}

/**
 * `detail` в ошибках API бывает либо строкой (400/404), либо массивом
 * объектов вида {type, loc, msg, input} — стандартная структура ошибок
 * валидации FastAPI/pydantic v2 при 422.
 */
function formatErrorDetail(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const loc = Array.isArray(d.loc) ? d.loc.join('.') : '';
        return loc ? `${loc}: ${d.msg}` : d.msg;
      })
      .join('; ');
  }
  try {
    return JSON.stringify(detail);
  } catch (_) {
    return String(detail);
  }
}

/**
 * Перевод "внутренней" формы меню (product/weight_g/date/calories/
 * protein/fat/carbs) в формат тела запроса реального API
 * (product_name/weight_grams/consumed_at/calories/proteins/fats/carbs).
 * consumed_at — по контракту допускает дату без времени ("YYYY-MM-DD"),
 * pydantic трактует её как полночь, так что отдельный выбор времени в
 * форме не нужен.
 */
function mapMealToApi(meal) {
  return {
    product_name: meal.product,
    weight_grams: meal.weight_g,
    consumed_at: meal.date,
    calories: meal.calories,
    proteins: meal.protein,
    fats: meal.fat,
    carbs: meal.carbs,
  };
}

/**
 * Обратный перевод ответа API во "внутреннюю" форму, которой пользуются
 * renderRow()/renderSummary(). Дата приёма пищи для отображения/группировки
 * берётся как первые 10 символов `consumed_at` (YYYY-MM-DD).
 */
function mapMealFromApi(apiMeal) {
  return {
    id: apiMeal.id,
    product: apiMeal.product_name,
    weight_g: apiMeal.weight_grams,
    date: typeof apiMeal.consumed_at === 'string' ? apiMeal.consumed_at.slice(0, 10) : '',
    calories: apiMeal.calories,
    protein: apiMeal.proteins,
    fat: apiMeal.fats,
    carbs: apiMeal.carbs,
  };
}

async function apiListMeals(date) {
  const qs = new URLSearchParams({ date }).toString();
  const rawMeals = await apiRequest(`/meals?${qs}`, { method: 'GET' });
  return Array.isArray(rawMeals) ? rawMeals.map(mapMealFromApi) : [];
}

async function apiCreateMeal(meal) {
  const rawMeal = await apiRequest('/meals', {
    method: 'POST',
    body: JSON.stringify(mapMealToApi(meal)),
  });
  return rawMeal ? mapMealFromApi(rawMeal) : null;
}

/**
 * GET /products?q=... - регистронезависимый поиск по подстроке в названии
 * продукта из встроенного справочника (storage/product_catalog.py).
 * Возвращает [] и для отсутствия совпадений, и для сетевой ошибки - вызывающий
 * код (runProductSearch) сам решает, что делать с пустым списком.
 */
async function apiSearchProducts(query) {
  const qs = new URLSearchParams({ q: query }).toString();
  const results = await apiRequest(`/products?${qs}`, { method: 'GET' });
  return Array.isArray(results) ? results : [];
}

/**
 * GET /products/portion?product_name=...&weight_grams=... - пересчёт
 * калорий/БЖУ порции. Формула "на_100г * вес / 100" реализована ОДИН раз, в
 * calculations.calculate_portion (Python); этот запрос - единственный способ,
 * которым фронтенд получает пересчитанные числа, чтобы не дублировать эту
 * арифметику в JS.
 */
async function apiGetPortion(productName, weightGrams) {
  const qs = new URLSearchParams({
    product_name: productName,
    weight_grams: String(weightGrams),
  }).toString();
  return apiRequest(`/products/portion?${qs}`, { method: 'GET' });
}

/* ---------------------------------------------------------------------- */
/* Загрузка и отрисовка таблицы за день                                   */
/* ---------------------------------------------------------------------- */

async function loadMeals(date) {
  setStatus('');
  setTableLoading();
  try {
    const meals = await apiListMeals(date);
    state.meals = Array.isArray(meals) ? meals : [];
    renderTable();
  } catch (err) {
    state.meals = [];
    renderTable();
    setStatus(err.message || 'Не удалось загрузить приёмы пищи.', 'warning');
  }
}

function setTableLoading() {
  els.tableBody.innerHTML = '<tr class="empty-row"><td colspan="6">Загрузка…</td></tr>';
  els.summaryRow.innerHTML = '';
}

function renderTable() {
  const meals = state.meals;
  els.tableBody.innerHTML = '';

  if (!meals.length) {
    const tr = document.createElement('tr');
    tr.className = 'empty-row';
    tr.innerHTML = '<td colspan="6">Нет приёмов пищи за выбранный день.</td>';
    els.tableBody.appendChild(tr);
  } else {
    for (const meal of meals) {
      els.tableBody.appendChild(renderRow(meal));
    }
  }

  renderSummary(meals);
}

function renderRow(meal) {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td>${escapeHtml(meal.product)}</td>
    <td class="num">${formatNumber(meal.weight_g)}</td>
    <td class="num">${formatNumber(meal.calories)}</td>
    <td class="num">${formatNumber(meal.protein)}</td>
    <td class="num">${formatNumber(meal.fat)}</td>
    <td class="num">${formatNumber(meal.carbs)}</td>
  `;
  return tr;
}

function renderSummary(meals) {
  const totals = meals.reduce(
    (acc, m) => {
      acc.weight_g += toNumber(m.weight_g);
      acc.calories += toNumber(m.calories);
      acc.protein += toNumber(m.protein);
      acc.fat += toNumber(m.fat);
      acc.carbs += toNumber(m.carbs);
      return acc;
    },
    { weight_g: 0, calories: 0, protein: 0, fat: 0, carbs: 0 }
  );

  els.summaryRow.innerHTML = `
    <td>Итого за день</td>
    <td class="num">${formatNumber(totals.weight_g)}</td>
    <td class="num">${formatNumber(totals.calories)}</td>
    <td class="num">${formatNumber(totals.protein)}</td>
    <td class="num">${formatNumber(totals.fat)}</td>
    <td class="num">${formatNumber(totals.carbs)}</td>
  `;
}

/* ---------------------------------------------------------------------- */
/* Автоподстановка продукта из справочника                                */
/* ---------------------------------------------------------------------- */

const debouncedSearchProducts = debounce(runProductSearch, 300);
const debouncedRecalcPortion = debounce(recalcPortionFromSelectedProduct, 250);

function onProductInput() {
  // Любое ручное изменение текста в поле "Продукт" аннулирует ранее
  // выбранный продукт справочника - изменение веса больше не будет
  // автоматически пересчитывать калории/БЖУ, пока пользователь не выберет
  // (тот же самый или другой) продукт из списка подсказок снова.
  if (state.selectedProduct) {
    state.selectedProduct = null;
    setCatalogHint('');
  }
  const query = els.product.value.trim();
  if (!query) {
    hideSuggestions();
    return;
  }
  debouncedSearchProducts(query);
}

async function runProductSearch(query) {
  let results;
  try {
    results = await apiSearchProducts(query);
  } catch (_err) {
    // Поиск - вспомогательная функция; если backend недоступен, просто не
    // показываем подсказки, не мешая ручному вводу калорий/БЖУ.
    hideSuggestions();
    return;
  }
  // Защита от "гонки" ответов: пока запрос летал по сети, пользователь мог
  // напечатать что-то другое (или очистить поле) - применяем результат
  // только если текст в поле всё ещё совпадает с тем, что искали.
  if (els.product.value.trim() !== query) return;
  renderSuggestions(results);
}

function renderSuggestions(products) {
  state.suggestions = products;
  state.activeSuggestionIndex = -1;
  els.productSuggestions.innerHTML = '';

  if (!products.length) {
    hideSuggestions();
    return;
  }

  products.forEach((product, index) => {
    const li = document.createElement('li');
    li.dataset.index = String(index);
    li.innerHTML = `
      <span class="suggestion-name">${escapeHtml(product.name)}</span>
      <span class="suggestion-meta">${formatNumber(product.calories)} ккал / 100 г</span>
    `;
    // mousedown (а не click) срабатывает раньше, чем blur поля ввода, и мы
    // отменяем его дефолтное действие - иначе поле теряло бы фокус (и по
    // таймеру скрывался список) прежде, чем успеет обработаться выбор.
    li.addEventListener('mousedown', (event) => {
      event.preventDefault();
      selectProduct(product);
    });
    els.productSuggestions.appendChild(li);
  });

  els.productSuggestions.hidden = false;
}

function hideSuggestions() {
  els.productSuggestions.hidden = true;
  els.productSuggestions.innerHTML = '';
  state.suggestions = [];
  state.activeSuggestionIndex = -1;
}

function onProductKeydown(event) {
  if (els.productSuggestions.hidden || !state.suggestions.length) return;
  const count = state.suggestions.length;

  if (event.key === 'ArrowDown') {
    event.preventDefault();
    state.activeSuggestionIndex = (state.activeSuggestionIndex + 1) % count;
    updateActiveSuggestionHighlight();
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    state.activeSuggestionIndex = (state.activeSuggestionIndex - 1 + count) % count;
    updateActiveSuggestionHighlight();
  } else if (event.key === 'Enter' && state.activeSuggestionIndex >= 0) {
    event.preventDefault();
    selectProduct(state.suggestions[state.activeSuggestionIndex]);
  } else if (event.key === 'Escape') {
    hideSuggestions();
  }
}

function updateActiveSuggestionHighlight() {
  const items = els.productSuggestions.querySelectorAll('li');
  items.forEach((li, idx) => li.classList.toggle('active', idx === state.activeSuggestionIndex));
}

function selectProduct(product) {
  state.selectedProduct = product;
  els.product.value = product.name;
  hideSuggestions();
  setCatalogHint(
    `Из справочника (на 100 г): ${formatNumber(product.calories)} ккал, ` +
      `Б ${formatNumber(product.protein)} / Ж ${formatNumber(product.fat)} / У ${formatNumber(product.carbs)}.`
  );
  recalcPortionFromSelectedProduct();
}

function onWeightInput() {
  if (!state.selectedProduct) return;
  debouncedRecalcPortion();
}

/**
 * Пересчитывает калории/БЖУ выбранного продукта на текущий вес из поля
 * "Вес, г" и подставляет результат в поля формы. Вызывается сразу при
 * выборе продукта из списка и повторно при каждом (debounced) изменении
 * веса, пока выбор продукта не сброшен.
 */
async function recalcPortionFromSelectedProduct() {
  const product = state.selectedProduct;
  if (!product) return;

  const weight = toNumber(els.weight.value);
  if (!(weight >= 0)) return;

  try {
    const portion = await apiGetPortion(product.name, weight);
    // Пока запрос летал по сети, пользователь мог сбросить/сменить выбор -
    // не затираем то, что он ввёл вручную в этом случае.
    if (state.selectedProduct !== product) return;
    els.calories.value = portion.calories;
    els.protein.value = portion.proteins;
    els.fat.value = portion.fats;
    els.carbs.value = portion.carbs;
  } catch (err) {
    els.formError.textContent = err.message || 'Не удалось пересчитать калории по весу.';
  }
}

function onNutritionFieldManualEdit() {
  // Пользователь правит калории/БЖУ вручную - это явный сигнал "я хочу
  // задать значение сам", поэтому отключаем автоматический пересчёт по весу
  // до тех пор, пока продукт не будет выбран из справочника снова.
  if (state.selectedProduct) {
    state.selectedProduct = null;
    setCatalogHint('Калории/БЖУ изменены вручную — автопересчёт по весу отключён до повторного выбора продукта.');
  }
}

function setCatalogHint(text) {
  els.catalogHint.textContent = text || '';
}

/* ---------------------------------------------------------------------- */
/* Форма добавления приёма пищи                                           */
/* ---------------------------------------------------------------------- */

async function onSubmit(event) {
  event.preventDefault();
  els.formError.textContent = '';

  const meal = {
    product: els.product.value.trim(),
    weight_g: toNumber(els.weight.value),
    date: els.mealDate.value,
    calories: toNumber(els.calories.value),
    protein: toNumber(els.protein.value),
    fat: toNumber(els.fat.value),
    carbs: toNumber(els.carbs.value),
  };

  const validationError = validateMeal(meal);
  if (validationError) {
    els.formError.textContent = validationError;
    return;
  }

  els.submitBtn.disabled = true;
  els.submitBtn.textContent = 'Сохранение…';
  try {
    await apiCreateMeal(meal);
    const savedDate = meal.date;
    els.form.reset();
    els.mealDate.value = savedDate;
    els.dayPicker.value = savedDate;
    state.selectedProduct = null;
    setCatalogHint('');
    hideSuggestions();
    await loadMeals(savedDate);
  } catch (err) {
    els.formError.textContent = err.message || 'Не удалось сохранить приём пищи.';
  } finally {
    els.submitBtn.disabled = false;
    els.submitBtn.textContent = 'Добавить приём пищи';
  }
}

function validateMeal(meal) {
  if (!meal.product) return 'Укажите название продукта.';
  if (!(meal.weight_g > 0)) return 'Вес должен быть положительным числом (в граммах).';
  if (!meal.date) return 'Укажите дату приёма пищи.';
  if (meal.calories < 0 || meal.protein < 0 || meal.fat < 0 || meal.carbs < 0) {
    return 'Калории и БЖУ не могут быть отрицательными.';
  }
  return '';
}

/* ---------------------------------------------------------------------- */
/* Утилиты                                                                 */
/* ---------------------------------------------------------------------- */

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function formatNumber(value) {
  const n = toNumber(value);
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function setStatus(message, level) {
  if (!message) {
    els.statusBanner.textContent = '';
    els.statusBanner.className = 'status-banner';
    return;
  }
  els.statusBanner.textContent = message;
  els.statusBanner.className = `status-banner visible ${level || 'warning'}`;
}
