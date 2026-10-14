use axum::{
    body::Body,
    extract::{Path, State},
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use futures_util::TryStreamExt;
use std::sync::Arc;
use tracing::warn;

use crate::movies::MovieCatalog;

#[derive(Clone)]
pub struct StreamState {
    pub upstream_url: String,
    pub catalog: MovieCatalog,
    pub http_client: reqwest::Client,
}

/// HTTP 206 Partial Content (Range Request) Handler for High-Performance Video Streaming
pub async fn handle_stream(
    Path((chat_id, msg_id)): Path<(i64, i64)>,
    headers: HeaderMap,
    State(state): State<Arc<StreamState>>,
) -> impl IntoResponse {
    let target_url = format!("{}/stream/{}/{}", state.upstream_url, chat_id, msg_id);

    let mut req = state.http_client.get(&target_url);

    // Forward incoming Range header if present
    if let Some(range) = headers.get(header::RANGE) {
        req = req.header(header::RANGE, range);
    }

    match req.send().await {
        Ok(upstream_resp) => {
            let status = StatusCode::from_u16(upstream_resp.status().as_u16())
                .unwrap_or(StatusCode::OK);

            let mut resp_headers = HeaderMap::new();

            // Copy essential streaming headers
            for (key, val) in upstream_resp.headers() {
                if key == header::CONTENT_TYPE
                    || key == header::CONTENT_LENGTH
                    || key == header::CONTENT_RANGE
                    || key == header::ACCEPT_RANGES
                    || key == header::CACHE_CONTROL
                {
                    resp_headers.insert(key.clone(), val.clone());
                }
            }

            // Ensure CORS and Accept-Ranges are explicitly set
            resp_headers.insert(
                header::ACCESS_CONTROL_ALLOW_ORIGIN,
                "*".parse().unwrap(),
            );
            resp_headers.insert(
                header::ACCESS_CONTROL_ALLOW_HEADERS,
                "Range, Content-Type".parse().unwrap(),
            );
            resp_headers.insert(
                header::ACCEPT_RANGES,
                "bytes".parse().unwrap(),
            );

            let body_stream = upstream_resp
                .bytes_stream()
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e));
            let body = Body::from_stream(body_stream);

            let mut response = Response::new(body);
            *response.status_mut() = status;
            *response.headers_mut() = resp_headers;
            response
        }
        Err(e) => {
            warn!("Failed to fetch upstream stream for {}/{}: {}", chat_id, msg_id, e);
            (
                StatusCode::BAD_GATEWAY,
                [("Access-Control-Allow-Origin", "*")],
                format!("Stream gateway error: {}", e),
            )
                .into_response()
        }
    }
}

/// HLS Master Playlist Handler (/hls/:chat_id/:msg_id/master.m3u8)
pub async fn handle_hls_master(
    Path((chat_id, msg_id)): Path<(i64, i64)>,
) -> impl IntoResponse {
    let m3u8 = format!(
        "#EXTM3U\n\
        #EXT-X-VERSION:3\n\
        #EXT-X-STREAM-INF:BANDWIDTH=5000000,NAME=\"Original\"\n\
        /hls/{}/{}/index.m3u8\n",
        chat_id, msg_id
    );

    (
        StatusCode::OK,
        [
            ("Content-Type", "application/vnd.apple.mpegurl"),
            ("Access-Control-Allow-Origin", "*"),
            ("Cache-Control", "no-cache"),
        ],
        m3u8,
    )
}

/// HLS Media Playlist Handler (/hls/:chat_id/:msg_id/index.m3u8)
pub async fn handle_hls_index(
    Path((chat_id, msg_id)): Path<(i64, i64)>,
    State(state): State<Arc<StreamState>>,
) -> impl IntoResponse {
    let movie_id = format!("{}_{}", chat_id, msg_id);
    let movie = state.catalog.get_by_id(&movie_id).await;

    let duration = movie.map(|m| m.duration_secs).unwrap_or(3600.0);
    let seg_duration = 6.0;
    let total_segs = ((duration / seg_duration).ceil() as u64).max(1);

    let mut lines = Vec::new();
    lines.push("#EXTM3U".to_string());
    lines.push("#EXT-X-VERSION:3".to_string());
    lines.push(format!("#EXT-X-TARGETDURATION:{}", seg_duration.ceil() as u64));
    lines.push("#EXT-X-MEDIA-SEQUENCE:0".to_string());
    lines.push("#EXT-X-PLAYLIST-TYPE:VOD".to_string());

    for i in 0..total_segs {
        let start = i as f64 * seg_duration;
        let rem = duration - start;
        let d = rem.min(seg_duration);
        lines.push(format!("#EXTINF:{:.3},", d));
        lines.push(format!("/hls/{}/{}/seg_{}.ts", chat_id, msg_id, i));
    }

    lines.push("#EXT-X-ENDLIST".to_string());
    let m3u8 = lines.join("\n") + "\n";

    (
        StatusCode::OK,
        [
            ("Content-Type", "application/vnd.apple.mpegurl"),
            ("Access-Control-Allow-Origin", "*"),
            ("Cache-Control", "no-cache"),
        ],
        m3u8,
    )
}

/// HLS Segment Proxy Handler (/hls/:chat_id/:msg_id/seg_:n.ts)
pub async fn handle_hls_segment(
    Path((chat_id, msg_id, seg_name)): Path<(i64, i64, String)>,
    State(state): State<Arc<StreamState>>,
) -> impl IntoResponse {
    let target_url = format!("{}/hls/{}/{}/source/{}", state.upstream_url, chat_id, msg_id, seg_name);

    match state.http_client.get(&target_url).send().await {
        Ok(resp) if resp.status().is_success() => {
            let body_stream = resp
                .bytes_stream()
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e));
            let body = Body::from_stream(body_stream);

            (
                StatusCode::OK,
                [
                    ("Content-Type", "video/MP2T"),
                    ("Access-Control-Allow-Origin", "*"),
                    ("Cache-Control", "public, max-age=31536000, immutable"),
                ],
                body,
            )
                .into_response()
        }
        _ => (
            StatusCode::NOT_FOUND,
            [("Access-Control-Allow-Origin", "*")],
            "Segment not found".to_string(),
        )
            .into_response(),
    }
}
