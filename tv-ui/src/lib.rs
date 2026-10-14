use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::JsFuture;
use web_sys::{
    Document, Element, HtmlElement, HtmlInputElement, HtmlVideoElement, KeyboardEvent,
    Request, RequestInit, RequestMode, Response, Window,
};
use serde::{Deserialize, Serialize};
use std::cell::RefCell;
use std::rc::Rc;

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

pub struct AppState {
    pub all_movies: Vec<Movie>,
    pub filtered_movies: Vec<Movie>,
    pub focused_index: usize,
    pub search_query: String,
    pub is_playing: bool,
    pub active_movie: Option<Movie>,
}

#[wasm_bindgen]
pub struct TvApp {
    state: Rc<RefCell<AppState>>,
}

#[wasm_bindgen]
impl TvApp {
    #[wasm_bindgen(constructor)]
    pub fn new() -> TvApp {
        let state = Rc::new(RefCell::new(AppState {
            all_movies: Vec::new(),
            filtered_movies: Vec::new(),
            focused_index: 0,
            search_query: String::new(),
            is_playing: false,
            active_movie: None,
        }));

        TvApp { state }
    }

    /// Initialize the TV App: loads movies from API, renders DOM, attaches remote key listeners
    pub fn init(&self) {
        let state = self.state.clone();

        wasm_bindgen_futures::spawn_local(async move {
            if let Ok(movies) = fetch_movies("").await {
                {
                    let mut s = state.borrow_mut();
                    s.all_movies = movies.clone();
                    s.filtered_movies = movies;
                }
                render_app(state.clone());
                setup_event_listeners(state.clone());
            }
        });
    }
}

async fn fetch_movies(query: &str) -> Result<Vec<Movie>, JsValue> {
    let window = web_sys::window().unwrap();
    let url = if query.is_empty() {
        "/api/movies".to_string()
    } else {
        format!("/api/movies?q={}", urlencoding::encode(query))
    };

    let mut opts = RequestInit::new();
    opts.set_method("GET");
    opts.set_mode(RequestMode::Cors);

    let request = Request::new_with_str_and_init(&url, &opts)?;
    let resp_val = JsFuture::from(window.fetch_with_request(&request)).await?;
    let resp: Response = resp_val.dyn_into()?;

    let json = JsFuture::from(resp.json()?).await?;
    let movies: Vec<Movie> = serde_wasm_bindgen::from_value(json).unwrap_or_default();
    Ok(movies)
}

fn render_app(state: Rc<RefCell<AppState>>) {
    let window = web_sys::window().unwrap();
    let document = window.document().unwrap();
    let app_root = match document.get_element_by_id("app") {
        Some(el) => el,
        None => return,
    };

    let s = state.borrow();
    let focused_movie = s.filtered_movies.get(s.focused_index).cloned();

    let backdrop = focused_movie
        .as_ref()
        .map(|m| m.backdrop_url.as_str())
        .unwrap_or("https://images.unsplash.com/photo-1518173946687-a4c8a383392e?w=1280");

    let title = focused_movie
        .as_ref()
        .map(|m| m.title.as_str())
        .unwrap_or("GAPT-CINEMA");

    let overview = focused_movie
        .as_ref()
        .map(|m| m.overview.as_str())
        .unwrap_or("เลือกภาพยนตร์เพื่อรับชมภาพความละเอียดสูงบนจอทีวี");

    let rating = focused_movie
        .as_ref()
        .map(|m| format!("{:.1}", m.vote_average))
        .unwrap_or_else(|| "8.0".to_string());

    let year = focused_movie
        .as_ref()
        .map(|m| m.release_date.chars().take(4).collect::<String>())
        .unwrap_or_else(|| "2024".to_string());

    // Generate HTML for movies grid
    let mut grid_html = String::new();
    for (idx, m) in s.filtered_movies.iter().enumerate() {
        let is_focused = idx == s.focused_index;
        let focus_class = if is_focused { "poster-card focused" } else { "poster-card" };
        let movie_year = m.release_date.chars().take(4).collect::<String>();

        grid_html.push_str(&format!(
            r#"<div class="{focus_class}" data-index="{idx}" tabindex="0">
                <div class="card-img-wrap">
                    <img src="{poster}" alt="{title}" loading="lazy" />
                    <span class="badge-rating">⭐ {rating:.1}</span>
                </div>
                <div class="card-info">
                    <h3 class="card-title">{title}</h3>
                    <span class="card-year">{movie_year}</span>
                </div>
            </div>"#,
            focus_class = focus_class,
            idx = idx,
            poster = m.poster_url,
            title = m.title,
            rating = m.vote_average,
            movie_year = movie_year
        ));
    }

    let search_val = &s.search_query;

    let html = format!(
        r#"<div class="cinema-backdrop" style="background-image: linear-gradient(to right, rgba(8, 12, 20, 0.95) 30%, rgba(8, 12, 20, 0.6) 70%, rgba(8, 12, 20, 0.95)), url('{backdrop}');">
            <header class="tv-header">
                <div class="brand">
                    <img src="cinema-icon.png" class="logo-icon" alt="GAPT-CINEMA" style="width: 32px; height: 32px; object-fit: contain;" />
                    <span class="logo-text">GAPT-CINEMA</span>
                </div>
                <div class="search-box">
                    <input type="text" id="tv-search" class="tv-search-input" placeholder="🔍 ค้นหาชื่อภาพยนตร์..." value="{search_val}" />
                </div>
                <div class="tv-clock" id="clock">TV LEANBACK</div>
            </header>

            <section class="hero-featured">
                <div class="hero-content">
                    <div class="hero-badges">
                        <span class="badge-quality">4K ULTRA HD</span>
                        <span class="badge-year">{year}</span>
                        <span class="badge-star">★ {rating}</span>
                    </div>
                    <h1 class="hero-title">{title}</h1>
                    <p class="hero-overview">{overview}</p>
                    <div class="hero-actions">
                        <button class="btn-play" id="btn-hero-play">▶ ดูภาพยนตร์ (กดปุ่มกลางรีโมท)</button>
                    </div>
                </div>
            </section>

            <section class="catalog-section">
                <h2 class="section-title">ภาพยนตร์ทั้งหมด ({total_count})</h2>
                <div class="movie-grid" id="movie-grid">
                    {grid_html}
                </div>
            </section>
        </div>"#,
        backdrop = backdrop,
        search_val = search_val,
        year = year,
        rating = rating,
        title = title,
        overview = overview,
        total_count = s.filtered_movies.len(),
        grid_html = grid_html
    );

    app_root.set_inner_html(&html);

    // Scroll focused element into view
    if let Some(focused_el) = document.query_selector(".poster-card.focused").ok().flatten() {
        if let Ok(html_el) = focused_el.dyn_into::<HtmlElement>() {
            html_el.scroll_into_view();
        }
    }
}

fn setup_event_listeners(state: Rc<RefCell<AppState>>) {
    let window = web_sys::window().unwrap();
    let document = window.document().unwrap();

    // Keydown handler for LG Magic Remote and keyboard arrows
    let state_key = state.clone();
    let on_keydown = Closure::wrap(Box::new(move |e: KeyboardEvent| {
        let code = e.key_code();
        let key = e.key();

        // 37 = Left, 38 = Up, 39 = Right, 40 = Down, 13 = Enter, 27 = Escape, 461 = LG Back
        let mut s = state_key.borrow_mut();

        // If player is active, Back closes it
        if s.is_playing {
            if code == 27 || code == 461 || key == "Backspace" || key == "Escape" {
                e.prevent_default();
                close_fullscreen_player(&mut s);
                drop(s);
                render_app(state_key.clone());
                return;
            }
            return;
        }

        let total = s.filtered_movies.len();
        if total == 0 {
            return;
        }

        match code {
            39 => { // ArrowRight
                e.prevent_default();
                if s.focused_index + 1 < total {
                    s.focused_index += 1;
                }
                drop(s);
                render_app(state_key.clone());
            }
            37 => { // ArrowLeft
                e.prevent_default();
                if s.focused_index > 0 {
                    s.focused_index -= 1;
                }
                drop(s);
                render_app(state_key.clone());
            }
            38 => { // ArrowUp
                e.prevent_default();
                if s.focused_index >= 5 {
                    s.focused_index -= 5;
                } else {
                    // Focus search bar
                    let doc = web_sys::window().unwrap().document().unwrap();
                    if let Some(input) = doc.get_element_by_id("tv-search") {
                        if let Ok(inp) = input.dyn_into::<HtmlInputElement>() {
                            inp.focus().ok();
                        }
                    }
                }
                drop(s);
                render_app(state_key.clone());
            }
            40 => { // ArrowDown
                e.prevent_default();
                if s.focused_index + 5 < total {
                    s.focused_index += 5;
                }
                drop(s);
                render_app(state_key.clone());
            }
            13 => { // Enter / OK button on remote
                e.prevent_default();
                if let Some(movie) = s.filtered_movies.get(s.focused_index).cloned() {
                    open_fullscreen_player(&mut s, movie);
                }
            }
            _ => {}
        }
    }) as Box<dyn FnMut(KeyboardEvent)>);

    document
        .add_event_listener_with_callback("keydown", on_keydown.as_ref().unchecked_ref())
        .ok();
    on_keydown.forget();
}

fn open_fullscreen_player(s: &mut AppState, movie: Movie) {
    s.is_playing = true;
    s.active_movie = Some(movie.clone());

    let window = web_sys::window().unwrap();
    let document = window.document().unwrap();

    let player_container = match document.get_element_by_id("fullscreen-player-container") {
        Some(el) => el,
        None => return,
    };

    player_container.set_class_name("fullscreen-player-visible");
    player_container.set_inner_html(&format!(
        r#"<div class="player-wrapper">
            <video id="tv-native-video" src="{stream_url}" controls autoplay class="video-screen"></video>
            <div class="player-overlay">
                <button id="btn-close-player" class="btn-close-player">✕ ย้อนกลับ</button>
                <div class="player-title">{title}</div>
            </div>
        </div>"#,
        stream_url = movie.stream_url,
        title = movie.title
    ));

    // Auto focus video element
    if let Some(video_el) = document.get_element_by_id("tv-native-video") {
        if let Ok(v) = video_el.dyn_into::<HtmlVideoElement>() {
            v.play().ok();
        }
    }
}

fn close_fullscreen_player(s: &mut AppState) {
    s.is_playing = false;
    s.active_movie = None;

    let window = web_sys::window().unwrap();
    let document = window.document().unwrap();

    if let Some(player_container) = document.get_element_by_id("fullscreen-player-container") {
        player_container.set_class_name("fullscreen-player-hidden");
        player_container.set_inner_html("");
    }
}
