use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::movies::{Movie, MovieCatalog};

#[derive(Debug, Deserialize)]
pub struct SearchParams {
    pub q: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub service: &'static str,
    pub version: &'static str,
}

pub async fn get_movies(
    Query(params): Query<SearchParams>,
    State(catalog): State<Arc<MovieCatalog>>,
) -> Json<Vec<Movie>> {
    let query = params.q.unwrap_or_default();
    let results = catalog.search(&query).await;
    Json(results)
}

pub async fn get_movie_by_id(
    Path(id): Path<String>,
    State(catalog): State<Arc<MovieCatalog>>,
) -> Result<Json<Movie>, StatusCode> {
    if let Some(movie) = catalog.get_by_id(&id).await {
        Ok(Json(movie))
    } else {
        Err(StatusCode::NOT_FOUND)
    }
}

pub async fn health_check() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        service: "tg-drive-rust-stream",
        version: "0.1.0",
    })
}
