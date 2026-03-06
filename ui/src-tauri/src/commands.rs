use crate::AppState;
use tauri::State;

type Result<T> = std::result::Result<T, String>;

fn map_err<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn health(state: State<'_, AppState>) -> Result<serde_json::Value> {
    let resp = state
        .client
        .get(format!("{}/api/health", state.base_url))
        .send()
        .await
        .map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_status(state: State<'_, AppState>) -> Result<serde_json::Value> {
    let resp = state
        .client
        .get(format!("{}/api/status", state.base_url))
        .send()
        .await
        .map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Predictions
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn predict_listing(state: State<'_, AppState>, url: String) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/predict/listing", state.base_url))
        .json(&serde_json::json!({ "url": url }))
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

#[tauri::command]
pub async fn predict_manual(
    state: State<'_, AppState>,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/predict/manual", state.base_url))
        .json(&payload)
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

#[tauri::command]
pub async fn predict_map_click(
    state: State<'_, AppState>,
    latitude: f64,
    longitude: f64,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/predict/map-click", state.base_url))
        .json(&serde_json::json!({ "latitude": latitude, "longitude": longitude }))
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Neighborhoods
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_neighborhoods(
    state: State<'_, AppState>,
    min_sales: Option<u32>,
    years: Option<u32>,
) -> Result<serde_json::Value> {
    let mut url = format!("{}/api/neighborhoods", state.base_url);
    let mut params = vec![];
    if let Some(ms) = min_sales {
        params.push(format!("min_sales={}", ms));
    }
    if let Some(y) = years {
        params.push(format!("years={}", y));
    }
    if !params.is_empty() {
        url = format!("{}?{}", url, params.join("&"));
    }

    let resp = state.client.get(&url).send().await.map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

#[tauri::command]
pub async fn get_neighborhood_detail(
    state: State<'_, AppState>,
    name: String,
    years: Option<u32>,
) -> Result<serde_json::Value> {
    let mut url = format!(
        "{}/api/neighborhoods/{}",
        state.base_url,
        urlencoding_encode(&name)
    );
    if let Some(y) = years {
        url = format!("{}?years={}", url, y);
    }

    let resp = state.client.get(&url).send().await.map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Not found");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

#[tauri::command]
pub async fn get_neighborhood_geojson(state: State<'_, AppState>) -> Result<serde_json::Value> {
    let resp = state
        .client
        .get(format!("{}/api/neighborhoods/geojson", state.base_url))
        .send()
        .await
        .map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Market
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_market_trend(
    state: State<'_, AppState>,
    months: Option<u32>,
) -> Result<serde_json::Value> {
    let url = match months {
        Some(m) => format!("{}/api/market/trend?months={}", state.base_url, m),
        None => format!("{}/api/market/trend", state.base_url),
    };
    let resp = state.client.get(&url).send().await.map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

#[tauri::command]
pub async fn get_market_summary(state: State<'_, AppState>) -> Result<serde_json::Value> {
    let resp = state
        .client
        .get(format!("{}/api/market/summary", state.base_url))
        .send()
        .await
        .map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Model Info
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_model_info(state: State<'_, AppState>) -> Result<serde_json::Value> {
    let resp = state
        .client
        .get(format!("{}/api/model/info", state.base_url))
        .send()
        .await
        .map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Affordability
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_affordability(
    state: State<'_, AppState>,
    budget: u32,
    down_pct: Option<f64>,
    hoa: Option<u32>,
) -> Result<serde_json::Value> {
    let mut url = format!("{}/api/afford/{}", state.base_url, budget);
    let mut params = vec![];
    if let Some(dp) = down_pct {
        params.push(format!("down_pct={}", dp));
    }
    if let Some(h) = hoa {
        params.push(format!("hoa={}", h));
    }
    if !params.is_empty() {
        url = format!("{}?{}", url, params.join("&"));
    }

    let resp = state.client.get(&url).send().await.map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Comparables
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_comparables(
    state: State<'_, AppState>,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/comps", state.base_url))
        .json(&payload)
        .send()
        .await
        .map_err(map_err)?;
    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Development Potential
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_property_potential(
    state: State<'_, AppState>,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/property/potential", state.base_url))
        .json(&payload)
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

#[tauri::command]
pub async fn get_property_potential_summary(
    state: State<'_, AppState>,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/property/potential/summary", state.base_url))
        .json(&payload)
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

#[tauri::command]
pub async fn get_improvement_simulation(
    state: State<'_, AppState>,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/property/improvement-sim", state.base_url))
        .json(&payload)
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Rental Analysis
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_rental_analysis(
    state: State<'_, AppState>,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/property/rental-analysis", state.base_url))
        .json(&payload)
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

#[tauri::command]
pub async fn get_rent_estimate(
    state: State<'_, AppState>,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/property/rent-estimate", state.base_url))
        .json(&payload)
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Faketor Chat
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn faketor_chat(
    state: State<'_, AppState>,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let resp = state
        .client
        .post(format!("{}/api/faketor/chat", state.base_url))
        .json(&payload)
        .send()
        .await
        .map_err(map_err)?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("Unknown error");
        return Err(format!("{}: {}", status, detail));
    }

    resp.json().await.map_err(map_err)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Simple percent-encoding for URL path segments.
fn urlencoding_encode(s: &str) -> String {
    s.replace(' ', "%20")
        .replace('/', "%2F")
        .replace('#', "%23")
}
