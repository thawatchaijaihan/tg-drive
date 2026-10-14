use crate::tmdb::TmdbClient;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{info, warn};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Movie {
    pub id: String,
    pub chat_id: i64,
    pub msg_id: i64,
    pub file_name: String,
    pub title: String,
    pub original_title: String,
    pub overview: String,
    pub poster_url: String,
    pub backdrop_url: String,
    pub release_date: String,
    pub vote_average: f32,
    pub duration_secs: f64,
    pub file_size: u64,
    pub stream_url: String,
    pub hls_url: String,
}

#[derive(Clone)]
pub struct MovieCatalog {
    movies: Arc<RwLock<HashMap<String, Movie>>>,
    tmdb: TmdbClient,
    base_url: String,
}

impl MovieCatalog {
    pub fn new(tmdb: TmdbClient, base_url: String) -> Self {
        Self {
            movies: Arc::new(RwLock::new(HashMap::new())),
            tmdb,
            base_url,
        }
    }

    /// Load movies from tg_stream.db SQLite database if available
    pub async fn load_from_db(&self, db_path: impl AsRef<Path>) {
        let path = db_path.as_ref();
        if !path.exists() {
            info!("Database file not found at {:?}, using default mock/sample catalog", path);
            self.seed_defaults().await;
            return;
        }

        let path_buf = path.to_path_buf();
        let tmdb = self.tmdb.clone();
        let base_url = self.base_url.clone();
        let catalog = self.clone();

        tokio::task::spawn_blocking(move || {
            match rusqlite::Connection::open(&path_buf) {
                Ok(conn) => {
                    let stmt = conn
                        .prepare("SELECT chat_id, msg_id, file_name, file_size, duration FROM videos WHERE mime_type LIKE 'video/%' OR file_name LIKE '%.mp4' OR file_name LIKE '%.mkv'")
                        .ok();

                    if let Some(mut stmt) = stmt {
                        let rows = stmt.query_map([], |row| {
                            Ok((
                                row.get::<_, i64>(0)?,
                                row.get::<_, i64>(1)?,
                                row.get::<_, String>(2)?,
                                row.get::<_, i64>(3)? as u64,
                                row.get::<_, f64>(4)?,
                            ))
                        });

                        if let Ok(rows) = rows {
                            let rt = tokio::runtime::Handle::current();
                            for r in rows.flatten() {
                                let (chat_id, msg_id, file_name, file_size, duration) = r;
                                let c = catalog.clone();
                                let t = tmdb.clone();
                                let b = base_url.clone();
                                rt.block_on(async move {
                                    c.add_or_update(chat_id, msg_id, file_name, file_size, duration, &t, &b).await;
                                });
                            }
                        }
                    }
                }
                Err(e) => {
                    warn!("Failed to open database {:?}: {}", path_buf, e);
                }
            }
        }).await.ok();

        // If no video was loaded from db, seed sample movies
        let count = self.movies.read().await.len();
        if count == 0 {
            info!("Database has 0 video records, adding popular and test items");
            self.seed_defaults().await;
        } else {
            info!("Loaded {} movies from database", count);
        }
    }

    pub async fn add_or_update(
        &self,
        chat_id: i64,
        msg_id: i64,
        file_name: String,
        file_size: u64,
        duration: f64,
        tmdb: &TmdbClient,
        base_url: &str,
    ) {
        let id = format!("{}_{}", chat_id, msg_id);
        
        // Enrich metadata with TMDB
        let tmdb_info = tmdb.fetch_movie_info(&file_name).await;

        let (title, original_title, overview, poster_url, backdrop_url, release_date, vote_average) = match tmdb_info {
            Some(info) => (
                info.title,
                info.original_title,
                info.overview,
                info.poster_url,
                info.backdrop_url,
                info.release_date,
                info.vote_average,
            ),
            None => (
                TmdbClient::clean_title(&file_name),
                file_name.clone(),
                "ภาพยนตร์จาก Telegram Cloud Storage".to_string(),
                "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=500&auto=format&fit=crop&q=60".to_string(),
                "https://images.unsplash.com/photo-1518173946687-a4c8a383392e?w=1280&auto=format&fit=crop&q=80".to_string(),
                "2024".to_string(),
                7.5,
            ),
        };

        let movie = Movie {
            id: id.clone(),
            chat_id,
            msg_id,
            file_name,
            title,
            original_title,
            overview,
            poster_url,
            backdrop_url,
            release_date,
            vote_average,
            duration_secs: duration,
            file_size,
            stream_url: format!("{}/stream/{}/{}", base_url, chat_id, msg_id),
            hls_url: format!("{}/hls/{}/{}/master.m3u8", base_url, chat_id, msg_id),
        };

        let mut lock = self.movies.write().await;
        lock.insert(id, movie);
    }

    /// Seed sample movies for testing and rich UI presentation
    pub async fn seed_defaults(&self) {
        let samples = vec![
            (
                4381915212,
                2,
                "ธี่หยด 2 (Tee Yod 2) 2024.1080p.WEB-DL.mp4",
                1843200000,
                6672.6,
            ),
            (
                -1003632932118,
                6,
                "Mood Booster.mp4",
                741105127,
                3746.2,
            ),
            (
                999999,
                1,
                "Big Buck Bunny Ultra Demo.mp4",
                15728640,
                600.0,
            ),
        ];

        for (chat_id, msg_id, name, size, dur) in samples {
            self.add_or_update(
                chat_id,
                msg_id,
                name.to_string(),
                size,
                dur,
                &self.tmdb,
                &self.base_url,
            )
            .await;
        }
    }

    /// Full-text search across movie title, original title, and overview
    pub async fn search(&self, query: &str) -> Vec<Movie> {
        let q = query.trim().to_lowercase();
        let list = self.movies.read().await;

        if q.is_empty() {
            let mut all: Vec<Movie> = list.values().cloned().collect();
            all.sort_by(|a, b| b.vote_average.partial_cmp(&a.vote_average).unwrap());
            return all;
        }

        let words: Vec<&str> = q.split_whitespace().collect();

        let mut results: Vec<Movie> = list
            .values()
            .filter(|m| {
                let text = format!("{} {} {} {}", m.title, m.original_title, m.file_name, m.overview).to_lowercase();
                words.iter().all(|w| text.contains(w))
            })
            .cloned()
            .collect();

        results.sort_by(|a, b| b.vote_average.partial_cmp(&a.vote_average).unwrap());
        results
    }

    pub async fn get_by_id(&self, id: &str) -> Option<Movie> {
        self.movies.read().await.get(id).cloned()
    }
}
