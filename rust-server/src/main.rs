mod api;
mod config;
mod movies;
mod stream;
mod tmdb;

use axum::{
    routing::get,
    Router,
};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use tower_http::cors::{Any, CorsLayer};
use tower_http::services::ServeDir;
use tracing::info;

use config::Config;
use movies::MovieCatalog;
use stream::StreamState;
use tmdb::TmdbClient;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();

    let config = Config::from_env();
    info!("Starting TG-Drive Rust Server on port {}", config.port);

    let tmdb = TmdbClient::new(config.tmdb_api_key.clone());
    let catalog = MovieCatalog::new(tmdb.clone(), config.base_url.clone());

    // Try finding database in common locations (e.g., server/tg_stream.db or current dir)
    let db_paths = [
        PathBuf::from("server/tg_stream.db"),
        PathBuf::from("../server/tg_stream.db"),
        PathBuf::from("tg_stream.db"),
        PathBuf::from("/home/ubuntu/tg-filestream/tg_stream.db"),
    ];

    let found_db = db_paths.into_iter().find(|p| p.exists());
    if let Some(db_path) = found_db {
        info!("Loading catalog from database at {:?}", db_path);
        catalog.load_from_db(db_path).await;
    } else {
        info!("No database found, seeding demo movies catalog");
        catalog.seed_defaults().await;
    }

    let stream_state = Arc::new(StreamState {
        upstream_url: config.upstream_stream_url.clone(),
        catalog: catalog.clone(),
        http_client: reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .build()
            .unwrap_or_default(),
    });

    let catalog_arc = Arc::new(catalog);

    // Build Axum Router
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let static_dir = PathBuf::from("rust-server/static");
    if !static_dir.exists() {
        std::fs::create_dir_all(&static_dir).ok();
    }

    let app = Router::new()
        // API routes
        .route("/api/health", get(api::health_check))
        .route("/api/movies", get(api::get_movies).with_state(catalog_arc.clone()))
        .route("/api/movies/:id", get(api::get_movie_by_id).with_state(catalog_arc.clone()))
        // Video Streaming & HLS routes
        .route("/stream/:chat_id/:msg_id", get(stream::handle_stream).with_state(stream_state.clone()))
        .route("/hls/:chat_id/:msg_id/master.m3u8", get(stream::handle_hls_master))
        .route("/hls/:chat_id/:msg_id/index.m3u8", get(stream::handle_hls_index).with_state(stream_state.clone()))
        .route("/hls/:chat_id/:msg_id/:seg_name", get(stream::handle_hls_segment).with_state(stream_state.clone()))
        // Static files (TV Leanback Web UI)
        .fallback_service(ServeDir::new(static_dir))
        .layer(cors);

    let addr = SocketAddr::from(([0, 0, 0, 0], config.port));
    info!("Server listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
