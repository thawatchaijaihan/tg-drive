use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub port: u16,
    pub base_url: String,
    pub tmdb_api_key: String,
    pub upstream_stream_url: String,
}

impl Config {
    pub fn from_env() -> Self {
        dotenvy::dotenv().ok();

        let port = std::env::var("PORT")
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(8086);

        let base_url = std::env::var("BASE_URL")
            .unwrap_or_else(|_| format!("http://localhost:{}", port));

        let tmdb_api_key = std::env::var("TMDB_API_KEY")
            .unwrap_or_else(|_| "4ff2e624c8c081e64627d3513a968bd0".to_string()); // Default demo/community key

        let upstream_stream_url = std::env::var("UPSTREAM_STREAM_URL")
            .unwrap_or_else(|_| "https://stream.capt-th.work".to_string());

        Self {
            port,
            base_url,
            tmdb_api_key,
            upstream_stream_url,
        }
    }
}
