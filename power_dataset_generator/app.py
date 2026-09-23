from __future__ import annotations

import os
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import CYBER_TARGETS, CYBER_TYPES, FAULT_TYPES, GRID_STRENGTHS, LOCATIONS, normal_config
from exporter import export_excel
from generator import SyntheticPowerSystemGenerator


APP_TITLE = "Power-System Dataset Generator — Synthetic Prototype"


class DatasetGeneratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1220x820")
        self.minsize(1050, 700)

        self.normal = normal_config()
        self.mode_var = tk.StringVar(value="Normal")
        self.vars = {}
        self.custom_widgets = []
        self.msg_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None

        self._build_style()
        self._build_ui()
        self._load_config_into_vars(self.normal)
        self._set_mode("Normal")
        self.after(100, self._poll_worker_messages)

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Changed.TLabel", foreground="#A64B00", font=("Segoe UI", 9, "bold"))

    def _build_ui(self):
        header = ttk.Frame(self, padding=(14, 12, 14, 6))
        header.pack(fill="x")
        ttk.Label(header, text="Power-System Dataset Generator", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="Synthetic prototype — replace demo electrical layer with validated simulator for research use",
            style="Hint.TLabel",
        ).pack(side="left", padx=(18, 0), pady=(5, 0))

        top = ttk.Frame(self, padding=(14, 4, 14, 8))
        top.pack(fill="x")

        size_box = ttk.LabelFrame(top, text="Dataset", style="Section.TLabelframe", padding=10)
        size_box.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Label(size_box, text="Rows (1–1,000,000)").grid(row=0, column=0, sticky="w")
        self.vars["rows"] = tk.StringVar(value="100000")
        ttk.Entry(size_box, textvariable=self.vars["rows"], width=18).grid(row=0, column=1, padx=8)
        ttk.Label(size_box, text="Excel's worksheet limit is 1,048,576 rows; this prototype caps data rows at 1,000,000.", style="Hint.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4,0))

        mode_box = ttk.LabelFrame(top, text="Simulation Mode", style="Section.TLabelframe", padding=10)
        mode_box.pack(side="left", fill="x", expand=True)
        ttk.Radiobutton(mode_box, text="Normal", value="Normal", variable=self.mode_var, command=lambda: self._set_mode("Normal")).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mode_box, text="Custom", value="Custom", variable=self.mode_var, command=lambda: self._set_mode("Custom")).grid(row=0, column=1, sticky="w", padx=(14,0))
        ttk.Label(mode_box, text="Normal uses the baseline configuration. Custom starts from the same baseline and lets you change selected factors.", style="Hint.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4,0))
        self.reset_btn = ttk.Button(mode_box, text="Reset Custom to Normal", command=self._reset_to_normal)
        self.reset_btn.grid(row=0, column=2, padx=(20,0))

        body = ttk.Frame(self, padding=(14, 0, 14, 8))
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=False)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10,0))

        self.notebook = ttk.Notebook(left, width=520, height=545)
        self.notebook.pack(fill="both", expand=True)

        self._build_operating_tab()
        self._build_fault_tab()
        self._build_cyber_tab()
        self._build_comm_tab()
        self._build_dataset_tab()

        preview_box = ttk.LabelFrame(right, text="Preview", style="Section.TLabelframe", padding=8)
        preview_box.pack(fill="both", expand=True)
        self.fig = Figure(figsize=(6.0, 4.4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Va preview")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Va")
        self.ax.grid(True, alpha=0.25)
        self.canvas = FigureCanvasTkAgg(self.fig, master=preview_box)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.preview_info = tk.StringVar(value="Press Preview to generate a small synthetic sample using the current settings.")
        ttk.Label(preview_box, textvariable=self.preview_info, wraplength=600, style="Hint.TLabel").pack(fill="x", pady=(6,0))

        actions = ttk.Frame(self, padding=(14, 4, 14, 12))
        actions.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(actions, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(actions, length=280, mode="determinate", maximum=100)
        self.progress.pack(side="left", padx=12)
        self.cancel_btn = ttk.Button(actions, text="Cancel", command=self._cancel_generation, state="disabled")
        self.cancel_btn.pack(side="right")
        self.generate_btn = ttk.Button(actions, text="Generate Excel Dataset", command=self._generate)
        self.generate_btn.pack(side="right", padx=(8,8))
        self.preview_btn = ttk.Button(actions, text="Preview", command=self._preview)
        self.preview_btn.pack(side="right")

    def _add_field(self, parent, row, label, key, default, width=16, combo_values=None, check=False, unit=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=5)
        if check:
            var = tk.BooleanVar(value=bool(default))
            widget = ttk.Checkbutton(parent, variable=var)
        else:
            var = tk.StringVar(value=str(default))
            if combo_values:
                widget = ttk.Combobox(parent, textvariable=var, values=combo_values, state="readonly", width=width)
            else:
                widget = ttk.Entry(parent, textvariable=var, width=width)
        widget.grid(row=row, column=1, sticky="w", padx=8, pady=5)
        if unit:
            ttk.Label(parent, text=unit, style="Hint.TLabel").grid(row=row, column=2, sticky="w")
        status = ttk.Label(parent, text="NORMAL", style="Hint.TLabel")
        status.grid(row=row, column=3, sticky="w", padx=(8,0))
        self.vars[key] = var
        self.custom_widgets.append((widget, key, status))
        var.trace_add("write", lambda *_args, k=key, s=status: self._update_changed_label(k, s))
        return widget

    def _build_operating_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Operating")
        fields = [
            ("Load level", "load_pct", self.normal["load_pct"], None, "%"),
            ("Power factor", "power_factor", self.normal["power_factor"], None, ""),
            ("Nominal phase RMS voltage", "nominal_voltage_rms_v", self.normal["nominal_voltage_rms_v"], None, "V"),
            ("Nominal RMS current @ 100% load", "nominal_current_rms_a", self.normal["nominal_current_rms_a"], None, "A"),
            ("Frequency", "frequency_hz", self.normal["frequency_hz"], None, "Hz"),
            ("DC-link voltage", "vdc_v", self.normal["vdc_v"], None, "V"),
            ("DC current @ 100% load", "idc_a", self.normal["idc_a"], None, "A"),
            ("Grid strength", "grid_strength", self.normal["grid_strength"], GRID_STRENGTHS, ""),
            ("Feeder impedance", "feeder_impedance_pu", self.normal["feeder_impedance_pu"], None, "pu"),
            ("Inverter 1 power share/reference", "inverter1_power_pct", self.normal["inverter1_power_pct"], None, "%"),
            ("Inverter 2 power share/reference", "inverter2_power_pct", self.normal["inverter2_power_pct"], None, "%"),
        ]
        for r, (label,key,val,combo,unit) in enumerate(fields):
            self._add_field(tab, r, label, key, val, combo_values=combo, unit=unit)

    def _build_fault_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Fault")
        self._add_field(tab, 0, "Enable fault", "fault_enabled", self.normal["fault_enabled"], check=True)
        self._add_field(tab, 1, "Fault type", "fault_type", self.normal["fault_type"], combo_values=FAULT_TYPES)
        self._add_field(tab, 2, "Location", "fault_location", self.normal["fault_location"], combo_values=LOCATIONS)
        self._add_field(tab, 3, "Fault resistance", "fault_resistance_ohm", self.normal["fault_resistance_ohm"], unit="Ω")
        self._add_field(tab, 4, "Start time", "fault_start_s", self.normal["fault_start_s"], unit="s")
        self._add_field(tab, 5, "Duration", "fault_duration_s", self.normal["fault_duration_s"], unit="s")
        ttk.Label(tab, text="Synthetic prototype rule: lower fault resistance produces a stronger voltage/current disturbance.", wraplength=440, style="Hint.TLabel").grid(row=7, column=0, columnspan=4, sticky="w", padx=8, pady=(12,0))

    def _build_cyber_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Cyber")
        self._add_field(tab, 0, "Enable cyberattack", "cyber_enabled", self.normal["cyber_enabled"], check=True)
        self._add_field(tab, 1, "Attack type", "cyber_type", self.normal["cyber_type"], combo_values=CYBER_TYPES)
        self._add_field(tab, 2, "Target sensor", "cyber_target", self.normal["cyber_target"], combo_values=CYBER_TARGETS)
        self._add_field(tab, 3, "Attack location", "cyber_location", self.normal["cyber_location"], combo_values=LOCATIONS)
        self._add_field(tab, 4, "Attack magnitude", "cyber_magnitude_pct", self.normal["cyber_magnitude_pct"], unit="%")
        self._add_field(tab, 5, "Start time", "cyber_start_s", self.normal["cyber_start_s"], unit="s")
        self._add_field(tab, 6, "Duration", "cyber_duration_s", self.normal["cyber_duration_s"], unit="s")
        self._add_field(tab, 7, "Ramp rate", "cyber_ramp_pct_per_s", self.normal["cyber_ramp_pct_per_s"], unit="%/s")
        self._add_field(tab, 8, "Replay delay", "cyber_replay_delay_s", self.normal["cyber_replay_delay_s"], unit="s")
        self._add_field(tab, 9, "Intermittent ON time", "cyber_intermit_on_s", self.normal["cyber_intermit_on_s"], unit="s")
        self._add_field(tab, 10, "Intermittent OFF time", "cyber_intermit_off_s", self.normal["cyber_intermit_off_s"], unit="s")

    def _build_comm_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Communication")
        self._add_field(tab, 0, "Enable communication impairment", "comm_enabled", self.normal["comm_enabled"], check=True)
        self._add_field(tab, 1, "Packet loss", "packet_loss_pct", self.normal["packet_loss_pct"], unit="%")
        self._add_field(tab, 2, "Fixed delay", "delay_ms", self.normal["delay_ms"], unit="ms")
        self._add_field(tab, 3, "Jitter", "jitter_ms", self.normal["jitter_ms"], unit="ms")
        self._add_field(tab, 4, "Repeated samples", "repeat_sample_pct", self.normal["repeat_sample_pct"], unit="%")
        self._add_field(tab, 5, "Quantization", "quantization_bits", self.normal["quantization_bits"], unit="bits")

    def _build_dataset_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Sampling")
        self._add_field(tab, 0, "Sampling rate", "sampling_rate_hz", self.normal["sampling_rate_hz"], unit="Hz")
        self._add_field(tab, 1, "Simulation duration", "simulation_duration_s", self.normal["simulation_duration_s"], unit="s/run")
        self._add_field(tab, 2, "Natural synthetic noise", "natural_noise_pct", self.normal["natural_noise_pct"], unit="%")
        self._add_field(tab, 3, "Random seed", "random_seed", self.normal["random_seed"])
        ttk.Label(tab, text="Rows are generated across as many simulation runs as required: rows ÷ (sampling rate × duration).", wraplength=440, style="Hint.TLabel").grid(row=5, column=0, columnspan=4, sticky="w", padx=8, pady=(12,0))

    def _load_config_into_vars(self, cfg):
        for key, var in self.vars.items():
            if key == "rows":
                continue
            if key in cfg:
                if isinstance(var, tk.BooleanVar):
                    var.set(bool(cfg[key]))
                else:
                    var.set(str(cfg[key]))

    def _reset_to_normal(self):
        rows = self.vars["rows"].get()
        self._load_config_into_vars(self.normal)
        self.vars["rows"].set(rows)
        self.status_var.set("Custom parameters reset to normal baseline.")

    def _set_mode(self, mode):
        self.mode_var.set(mode)
        normal = mode == "Normal"
        for widget, key, _status in self.custom_widgets:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state="disabled" if normal else "readonly")
                else:
                    widget.configure(state="disabled" if normal else "normal")
            except tk.TclError:
                pass
        self.reset_btn.configure(state="disabled" if normal else "normal")
        if normal:
            self._load_config_into_vars(self.normal)
            self.status_var.set("Normal mode: baseline configuration locked.")
        else:
            self.status_var.set("Custom mode: change only the factors you want to study.")

    def _update_changed_label(self, key, label_widget):
        try:
            if self.mode_var.get() == "Normal":
                label_widget.configure(text="NORMAL", style="Hint.TLabel")
                return
            var = self.vars[key]
            current = var.get()
            base = self.normal.get(key)
            if isinstance(var, tk.BooleanVar):
                changed = bool(current) != bool(base)
            else:
                changed = str(current) != str(base)
            label_widget.configure(text="CUSTOM" if changed else "NORMAL", style="Changed.TLabel" if changed else "Hint.TLabel")
        except Exception:
            pass

    @staticmethod
    def _to_float(value, name):
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"{name} must be a number.")

    @staticmethod
    def _to_int(value, name):
        try:
            return int(float(value))
        except ValueError:
            raise ValueError(f"{name} must be an integer.")

    def _collect_config(self):
        cfg = normal_config()
        cfg["mode"] = self.mode_var.get()
        cfg["rows"] = self._to_int(self.vars["rows"].get(), "Rows")
        if not (1 <= cfg["rows"] <= 1_000_000):
            raise ValueError("Rows must be between 1 and 1,000,000 for Excel output.")

        if self.mode_var.get() == "Custom":
            float_keys = [
                "load_pct", "power_factor", "nominal_voltage_rms_v", "nominal_current_rms_a", "frequency_hz",
                "vdc_v", "idc_a", "feeder_impedance_pu", "inverter1_power_pct", "inverter2_power_pct",
                "fault_resistance_ohm", "fault_start_s", "fault_duration_s", "cyber_magnitude_pct",
                "cyber_start_s", "cyber_duration_s", "cyber_ramp_pct_per_s", "cyber_replay_delay_s",
                "cyber_intermit_on_s", "cyber_intermit_off_s", "packet_loss_pct", "delay_ms", "jitter_ms",
                "repeat_sample_pct", "simulation_duration_s", "natural_noise_pct",
            ]
            int_keys = ["sampling_rate_hz", "quantization_bits", "random_seed"]
            bool_keys = ["fault_enabled", "cyber_enabled", "comm_enabled"]
            str_keys = ["grid_strength", "fault_type", "fault_location", "cyber_type", "cyber_target", "cyber_location"]
            for k in float_keys:
                cfg[k] = self._to_float(self.vars[k].get(), k)
            for k in int_keys:
                cfg[k] = self._to_int(self.vars[k].get(), k)
            for k in bool_keys:
                cfg[k] = bool(self.vars[k].get())
            for k in str_keys:
                cfg[k] = self.vars[k].get()
        else:
            # Normal mode intentionally ignores hidden/custom widget values.
            cfg.update({k: v for k, v in self.normal.items() if k != "rows"})
            cfg["rows"] = self._to_int(self.vars["rows"].get(), "Rows")
            cfg["mode"] = "Normal"

        # Basic range validation relevant to both preview and export.
        if cfg["sampling_rate_hz"] <= 0 or cfg["simulation_duration_s"] <= 0:
            raise ValueError("Sampling rate and simulation duration must be greater than zero.")
        if not (0 < cfg["power_factor"] <= 1.0):
            raise ValueError("Power factor must be greater than 0 and no more than 1.0.")
        if cfg["packet_loss_pct"] < 0 or cfg["packet_loss_pct"] > 100:
            raise ValueError("Packet loss must be between 0 and 100%.")
        if cfg["repeat_sample_pct"] < 0 or cfg["repeat_sample_pct"] > 100:
            raise ValueError("Repeated samples must be between 0 and 100%.")
        return cfg

    def _preview(self):
        try:
            cfg = self._collect_config()
            # Preview the full simulation time span while bounding plotted/generated points.
            # If the requested sampling rate is very high, use a lower preview-only rate;
            # the exported dataset still uses the exact requested rate.
            preview_cfg = dict(cfg)
            duration = max(float(cfg["simulation_duration_s"]), 1e-6)
            preview_rate = min(int(cfg["sampling_rate_hz"]), max(200, int(10_000 / duration)))
            preview_cfg["sampling_rate_hz"] = preview_rate
            preview_cfg["rows"] = max(100, min(10_000, int(round(preview_rate * duration))))
            generator = SyntheticPowerSystemGenerator(preview_cfg)
            data = generator.preview(preview_cfg["rows"])
        except Exception as exc:
            messagebox.showerror("Preview error", str(exc))
            return

        self.ax.clear()
        self.ax.plot(data["time_s"], data["Va"], linewidth=1.0, label="Va")
        if cfg["cyber_enabled"] and cfg["cyber_target"] != "Va":
            target = cfg["cyber_target"]
            if target in data:
                self.ax.plot(data["time_s"], data[target], linewidth=0.9, alpha=0.8, label=target)
        self.ax.set_title(f"Synthetic preview — {cfg['mode']} mode")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Signal value")
        self.ax.grid(True, alpha=0.25)
        self.ax.legend(loc="upper right")
        self.fig.tight_layout()
        self.canvas.draw()

        changed = []
        if cfg["fault_enabled"]:
            changed.append(f"fault={cfg['fault_type']} @ {cfg['fault_location']}")
        if cfg["cyber_enabled"]:
            changed.append(f"cyber={cfg['cyber_type']} on {cfg['cyber_target']} ({cfg['cyber_magnitude_pct']}%)")
        if cfg["comm_enabled"]:
            changed.append("communication impairment enabled")
        desc = ", ".join(changed) if changed else "baseline/normal scenario"
        self.preview_info.set(f"Previewed the full {cfg['simulation_duration_s']} s timeline using {len(data['time_s']):,} display samples ({desc}). Export still uses the requested {cfg['sampling_rate_hz']} Hz. Synthetic demo data only.")

    def _generate(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            cfg = self._collect_config()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"PowerDataset_{timestamp}.xlsx"
        path = filedialog.asksaveasfilename(
            title="Save generated Excel dataset",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not path:
            return

        self.cancel_event.clear()
        self.progress["value"] = 0
        self.generate_btn.configure(state="disabled")
        self.preview_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.status_var.set("Starting dataset generation...")

        def progress_callback(frac, text):
            self.msg_queue.put(("progress", frac, text))

        def run():
            try:
                actual = export_excel(path, cfg, progress_callback=progress_callback, cancel_check=self.cancel_event.is_set)
                self.msg_queue.put(("done", actual))
            except Exception as exc:
                self.msg_queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _cancel_generation(self):
        self.cancel_event.set()
        self.status_var.set("Cancelling after the current chunk...")

    def _poll_worker_messages(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if msg[0] == "progress":
                    _, frac, text = msg
                    self.progress["value"] = max(0, min(100, frac * 100))
                    self.status_var.set(text)
                elif msg[0] == "done":
                    _, path = msg
                    self.progress["value"] = 100
                    self.status_var.set(f"Saved: {path}")
                    self.generate_btn.configure(state="normal")
                    self.preview_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    messagebox.showinfo("Dataset generated", f"New Excel dataset created successfully:\n\n{path}")
                elif msg[0] == "error":
                    _, text = msg
                    self.status_var.set(text)
                    self.generate_btn.configure(state="normal")
                    self.preview_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    messagebox.showerror("Generation failed", text)
        except queue.Empty:
            pass
        self.after(100, self._poll_worker_messages)


if __name__ == "__main__":
    app = DatasetGeneratorApp()
    app.mainloop()
