use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TmdbMovieInfo {
    pub title: String,
    pub original_title: String,
    pub overview: String,
    pub poster_url: String,
    pub backdrop_url: String,
    pub release_date: String,
    pub vote_average: f32,
}

#[derive(Debug, Deserialize)]
struct TmdbSearchResponse {
    results: Vec<TmdbSearchResult>,
}

#[derive(Debug, Deserialize)]
struct TmdbSearchResult {
    title: Option<String>,
    original_title: Option<String>,
    overview: Option<String>,
    poster_path: Option<String>,
    backdrop_path: Option<String>,
    release_date: Option<String>,
    vote_average: Option<f32>,
}

#[derive(Clone)]
pub struct TmdbClient {
    client: reqwest::Client,
    api_key: String,
    cache: Arc<RwLock<HashMap<String, TmdbMovieInfo>>>,
}

impl TmdbClient {
    pub fn new(api_key: String) -> Self {
        Self {
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(10))
                .build()
                .unwrap_or_default(),
            api_key,
            cache: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Extract clean title for search from filename (e.g., removes 1080p, WEBRip, extensions)
    pub fn clean_title(raw_name: &str) -> String {
        let mut name = raw_name.to_string();

        // Strip file extension
        if let Some(dot_idx) = name.rfind('.') {
            name = name[..dot_idx].to_string();
        }

        // Replace common separator characters with spaces
        name = name.replace(['.', '_', '-'], " ");

        // Remove resolution and technical metadata tags
        let re_meta = Regex::new(r"(?i)\b(1080p|720p|2160p|4k|bluray|web-dl|webrip|hdrip|x264|x265|hevc|aac|dts|truehd|remux|h264|h265)\b").unwrap();
        name = re_meta.replace_all(&name, "").to_string();

        // Extract year if present
        let re_year = Regex::new(r"\b(19\d\d|20\d\d)\b").unwrap();
        let cleaned = re_year.replace_all(&name, "").to_string();

        let result = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
        if result.is_empty() {
            raw_name.to_string()
        } else {
            result
        }
    }

    /// Search TMDB for movie details with Thai language support
    pub async fn fetch_movie_info(&self, search_query: &str) -> Option<TmdbMovieInfo> {
        let cleaned = Self::clean_title(search_query);
        let cache_key = cleaned.to_lowercase();

        // Check in-memory cache
        {
            let cache = self.cache.read().await;
            if let Some(info) = cache.get(&cache_key) {
                return Some(info.clone());
            }
        }

        // Search with Thai language first
        let url_th = format!(
            "https://api.themoviedb.org/3/search/movie?api_key={}&query={}&language=th-TH&include_adult=false",
            self.api_key,
            urlencoding::encode(&cleaned)
        );

        if let Ok(resp) = self.client.get(&url_th).send().await {
            if let Ok(data) = resp.json::<TmdbSearchResponse>().await {
                if let Some(item) = data.results.into_iter().next() {
                    let poster = item
                        .poster_path
                        .map(|p| format!("https://image.tmdb.org/t/p/w500{}", p))
                        .unwrap_or_else(|| "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=500&auto=format&fit=crop&q=60".to_string());

                    let backdrop = item
                        .backdrop_path
                        .map(|b| format!("https://image.tmdb.org/t/p/original{}", b))
                        .unwrap_or_else(|| "https://images.unsplash.com/photo-1518173946687-a4c8a383392e?w=1280&auto=format&fit=crop&q=80".to_string());

                    let movie_info = TmdbMovieInfo {
                        title: item.title.unwrap_or_else(|| cleaned.clone()),
                        original_title: item.original_title.unwrap_or_default(),
                        overview: item.overview.unwrap_or_else(|| "ไม่มีข้อมูลเรื่องย่อ".to_string()),
                        poster_url: poster,
                        backdrop_url: backdrop,
                        release_date: item.release_date.unwrap_or_else(|| "2024".to_string()),
                        vote_average: item.vote_average.unwrap_or(7.5),
                    };

                    let mut cache = self.cache.write().await;
                    cache.insert(cache_key, movie_info.clone());
                    return Some(movie_info);
                }
            }
        }

        None
    }
}
