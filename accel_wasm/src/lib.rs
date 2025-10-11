use wasm_bindgen::prelude::*;

#[wasm_bindgen]
pub struct Detector {
    ema: f64,
    have_ema: bool,
    alpha: f64,
    /// motion threshold **in m/s^2** (deviation from 1g)
    thresh: f64,
}

#[wasm_bindgen]
impl Detector {
    #[wasm_bindgen(constructor)]
    pub fn new(alpha: f64, thresh: f64) -> Detector {
        Detector { ema: 0.0, have_ema: false, alpha, thresh }
    }

    /// Provide counts and g-range (LSB per g). Returns:
    /// [ax_ms2, ay_ms2, az_ms2, |a|_ms2, ema_ms2, alarm_bool]
    pub fn process_counts(&mut self, x: i32, y: i32, z: i32, g_range: i32) -> js_sys::Array {
        let g2ms2 = 9.80665_f64;
        // Correct scale: g = counts / (LSB_per_g)
        let g_per_lsb = 1.0 / (g_range as f64);

        let ax = (x as f64) * g_per_lsb * g2ms2;
        let ay = (y as f64) * g_per_lsb * g2ms2;
        let az = (z as f64) * g_per_lsb * g2ms2;

        let mag = (ax*ax + ay*ay + az*az).sqrt();

        if !self.have_ema {
            self.ema = mag;
            self.have_ema = true;
        } else {
            self.ema = self.alpha * mag + (1.0 - self.alpha) * self.ema;
        }

        let dev = (mag - g2ms2).abs(); // deviation from 1g
        let alarm = dev >= self.thresh;

        let out = js_sys::Array::new();
        out.push(&ax.into());
        out.push(&ay.into());
        out.push(&az.into());
        out.push(&mag.into());
        out.push(&self.ema.into());
        out.push(&JsValue::from_bool(alarm));
        out
    }
}
