#!/usr/bin/env python3
"""
WORK IN PROGRESS/ 

GUI for creating June Zero worlds.

This application provides a graphical form-based interface for configuring
and running the world creation script.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import subprocess
import threading
import os
import yaml


class ConfigForm(ttk.Frame):
    """Form widget for the main config.yaml settings."""

    def __init__(self, parent, config_path, **kwargs):
        super().__init__(parent, **kwargs)
        self.config_path = config_path
        self.widgets = {}

        # Create scrollable frame
        self.canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_frame = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind canvas resize to update scrollable frame width
        self.canvas.bind('<Configure>', self._on_canvas_configure)

        # Enable mousewheel scrolling
        self.bind_mousewheel()

        # Build the form
        self.build_form()

        # Load current config
        self.load_config()

    def _on_canvas_configure(self, event):
        """Update the scrollable frame width when canvas is resized."""
        self.canvas.itemconfig(self.canvas_frame, width=event.width)

    def bind_mousewheel(self):
        """Bind mousewheel scrolling."""
        def _on_mousewheel(event):
            # For macOS
            self.canvas.yview_scroll(int(-1 * (event.delta)), "units")

        def _on_mousewheel_linux(event):
            # For Linux
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")

        # Bind to frame and all children
        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)  # Windows/macOS
        self.canvas.bind_all("<Button-4>", _on_mousewheel_linux)  # Linux
        self.canvas.bind_all("<Button-5>", _on_mousewheel_linux)  # Linux

    def build_form(self):
        """Build the configuration form."""
        row = 0

        # Configure column weights
        self.scrollable_frame.columnconfigure(0, weight=0, minsize=200)  # Labels
        self.scrollable_frame.columnconfigure(1, weight=1)  # Entry fields
        self.scrollable_frame.columnconfigure(2, weight=0)  # Browse buttons

        # ========== GEOGRAPHY SECTION ==========
        geo_label = ttk.Label(self.scrollable_frame, text="Geography Configuration",
                             font=('Arial', 12, 'bold'))
        geo_label.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=(10, 5), padx=10)
        row += 1

        # Data directory
        self.add_entry(row, "Data Directory:", "geography.data_dir",
                      tooltip="Path to geography data files")
        row += 1

        # Load all checkbox
        self.add_checkbox(row, "Load All Units:", "geography.load_all",
                         tooltip="Load all geographical units (ignores filters)")
        row += 1

        # Filter section
        filter_label = ttk.Label(self.scrollable_frame, text="Filters:",
                                font=('Arial', 10, 'bold'))
        filter_label.grid(row=row, column=0, sticky=tk.W, pady=(10, 5), padx=30)
        row += 1

        # Filter level
        self.add_combobox(row, "Filter Level:", "geography.filter.level",
                         values=["", "LGU", "MGU", "SGU"],
                         tooltip="Level to filter on (leave empty for all)")
        row += 1

        # Filter codes
        self.add_entry(row, "Filter Codes:", "geography.filter.codes",
                      tooltip="Comma-separated codes (e.g., London,Birmingham)")
        row += 1

        # Filter file
        self.add_file_entry(row, "Filter File:", "geography.filter.file",
                           tooltip="Path to file with codes (one per line)")
        row += 1

        # ========== POPULATION SECTION ==========
        pop_label = ttk.Label(self.scrollable_frame, text="Population Configuration",
                             font=('Arial', 12, 'bold'))
        pop_label.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=(20, 5), padx=10)
        row += 1

        self.add_entry(row, "Data Directory:", "population.data_dir",
                      tooltip="Path to population data files")
        row += 1

        self.add_entry(row, "Demographics Male File:", "population.demographics_male_file",
                      tooltip="Filename for male demographics CSV")
        row += 1

        self.add_entry(row, "Demographics Female File:", "population.demographics_female_file",
                      tooltip="Filename for female demographics CSV")
        row += 1

        # ========== VENUES SECTION ==========
        venue_label = ttk.Label(self.scrollable_frame, text="Venues Configuration",
                               font=('Arial', 12, 'bold'))
        venue_label.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=(20, 5), padx=10)
        row += 1

        self.add_entry(row, "Data Directory:", "venues.data_dir",
                      tooltip="Path to venue data files")
        row += 1

        self.add_file_entry(row, "Config File:", "venues.config_file",
                           tooltip="Path to venues YAML configuration")
        row += 1

        self.add_entry(row, "Export File:", "venues.export_file",
                      tooltip="Output file for venue allocations")
        row += 1

        # ========== HOUSEHOLDS SECTION ==========
        hh_label = ttk.Label(self.scrollable_frame, text="Households Configuration",
                            font=('Arial', 12, 'bold'))
        hh_label.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=(20, 5), padx=10)
        row += 1

        self.add_entry(row, "Data Directory:", "households.data_dir",
                      tooltip="Path to household data files")
        row += 1

        self.add_entry(row, "Data File:", "households.data_file",
                      tooltip="Household composition data CSV")
        row += 1

        self.add_file_entry(row, "Config File:", "households.config_file",
                           tooltip="Household configuration YAML")
        row += 1

        self.add_file_entry(row, "Strategy File:", "households.strategy_file",
                           tooltip="Allocation strategy YAML")
        row += 1

        self.add_entry(row, "Export File:", "households.export_file",
                      tooltip="Output file for household allocations")
        row += 1

        # Save button at bottom
        save_btn = ttk.Button(self.scrollable_frame, text="💾 Save Configuration",
                             command=self.save_config)
        save_btn.grid(row=row, column=0, columnspan=3, pady=20, padx=10)

    def add_entry(self, row, label_text, key, tooltip=""):
        """Add a text entry field."""
        label = ttk.Label(self.scrollable_frame, text=label_text)
        label.grid(row=row, column=0, sticky=tk.W, padx=(10, 5), pady=5)

        entry = ttk.Entry(self.scrollable_frame, width=60)
        entry.grid(row=row, column=1, columnspan=2, sticky=tk.W+tk.E, padx=5, pady=5)

        if tooltip:
            self.create_tooltip(entry, tooltip)

        self.widgets[key] = entry

    def add_checkbox(self, row, label_text, key, tooltip=""):
        """Add a checkbox field."""
        label = ttk.Label(self.scrollable_frame, text=label_text)
        label.grid(row=row, column=0, sticky=tk.W, padx=(10, 5), pady=5)

        var = tk.BooleanVar()
        checkbox = ttk.Checkbutton(self.scrollable_frame, variable=var)
        checkbox.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)

        if tooltip:
            self.create_tooltip(checkbox, tooltip)

        self.widgets[key] = var

    def add_combobox(self, row, label_text, key, values, tooltip=""):
        """Add a dropdown/combobox field."""
        label = ttk.Label(self.scrollable_frame, text=label_text)
        label.grid(row=row, column=0, sticky=tk.W, padx=(10, 5), pady=5)

        combobox = ttk.Combobox(self.scrollable_frame, values=values, width=57)
        combobox.grid(row=row, column=1, columnspan=2, sticky=tk.W+tk.E, padx=5, pady=5)

        if tooltip:
            self.create_tooltip(combobox, tooltip)

        self.widgets[key] = combobox

    def add_file_entry(self, row, label_text, key, tooltip=""):
        """Add a file path entry with browse button."""
        label = ttk.Label(self.scrollable_frame, text=label_text)
        label.grid(row=row, column=0, sticky=tk.W, padx=(10, 5), pady=5)

        entry = ttk.Entry(self.scrollable_frame)
        entry.grid(row=row, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        browse_btn = ttk.Button(self.scrollable_frame, text="Browse...",
                               command=lambda: self.browse_file(entry))
        browse_btn.grid(row=row, column=2, sticky=tk.E, padx=5, pady=5)

        if tooltip:
            self.create_tooltip(entry, tooltip)

        self.widgets[key] = entry

    def browse_file(self, entry_widget):
        """Open file browser and set entry value."""
        filename = filedialog.askopenfilename(
            title="Select File",
            initialdir=os.path.dirname(self.config_path)
        )
        if filename:
            # Convert to relative path if possible
            try:
                project_root = os.path.dirname(os.path.dirname(self.config_path))
                rel_path = os.path.relpath(filename, project_root)
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, rel_path)
            except ValueError:
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, filename)

    def create_tooltip(self, widget, text):
        """Create a tooltip for a widget."""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            label = ttk.Label(tooltip, text=text, background="#ffffe0",
                            relief=tk.SOLID, borderwidth=1)
            label.pack()
            widget.tooltip = tooltip

        def on_leave(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()
                del widget.tooltip

        widget.bind('<Enter>', on_enter)
        widget.bind('<Leave>', on_leave)

    def get_nested_value(self, data, key_path):
        """Get value from nested dict using dot notation."""
        keys = key_path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def set_nested_value(self, data, key_path, value):
        """Set value in nested dict using dot notation."""
        keys = key_path.split('.')
        current = data
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    def load_config(self):
        """Load configuration from YAML file."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = yaml.safe_load(f)

                # Populate widgets
                for key, widget in self.widgets.items():
                    value = self.get_nested_value(config, key)
                    if value is not None:
                        if isinstance(widget, tk.BooleanVar):
                            widget.set(value)
                        elif isinstance(widget, (ttk.Entry, ttk.Combobox)):
                            widget.delete(0, tk.END)
                            # Handle list values
                            if isinstance(value, list):
                                widget.insert(0, ', '.join(str(v) for v in value))
                            else:
                                widget.insert(0, str(value) if value else "")
        except Exception as e:
            messagebox.showerror("Load Error", f"Error loading config:\n{str(e)}")

    def save_config(self):
        """Save configuration to YAML file."""
        try:
            # Load existing config
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
            else:
                config = {}

            # Update with widget values
            for key, widget in self.widgets.items():
                if isinstance(widget, tk.BooleanVar):
                    value = widget.get()
                elif isinstance(widget, (ttk.Entry, ttk.Combobox)):
                    value = widget.get().strip()
                    # Handle comma-separated codes
                    if 'codes' in key and value:
                        value = [v.strip() for v in value.split(',') if v.strip()]
                    # Convert empty strings to None for optional fields
                    elif value == "":
                        value = None if 'file' in key or 'level' in key else value
                else:
                    continue

                self.set_nested_value(config, key, value)

            # Save to file
            with open(self.config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            messagebox.showinfo("Saved", "Configuration saved successfully!")
        except Exception as e:
            messagebox.showerror("Save Error", f"Error saving config:\n{str(e)}")


class StepWidget(ttk.Frame):
    """Widget for a single allocation step."""

    def __init__(self, parent, step_data=None, on_delete=None, step_number=1, **kwargs):
        super().__init__(parent, **kwargs)
        self.step_data = step_data or {}
        self.on_delete = on_delete
        self.step_number = step_number
        self.pattern_widgets = []
        self.demotion_rule_widgets = []

        # Create the step UI
        self.build_ui()

        # Load data if provided
        if step_data:
            self.load_data(step_data)

    def build_ui(self):
        """Build the step widget UI."""
        # Main container with border
        container = ttk.LabelFrame(self, text=f"Step {self.step_number}", padding=10)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create inner frame for grid layout
        inner_frame = ttk.Frame(container)
        inner_frame.pack(fill=tk.BOTH, expand=True)

        # Basic fields
        row = 0

        # Delete button
        delete_btn = ttk.Button(inner_frame, text="✕ Delete Step", command=self._on_delete)
        delete_btn.grid(row=row, column=0, columnspan=2, sticky=tk.E, pady=(0, 10))
        row += 1

        # Name
        ttk.Label(inner_frame, text="Name:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=5)
        self.name_entry = ttk.Entry(inner_frame, width=50)
        self.name_entry.grid(row=row, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        row += 1

        # Type
        ttk.Label(inner_frame, text="Type:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=5)
        self.type_combo = ttk.Combobox(inner_frame, values=["household", "venue"], width=47, state="readonly")
        self.type_combo.grid(row=row, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        self.type_combo.bind("<<ComboboxSelected>>", self._on_type_changed)
        row += 1

        # Description
        ttk.Label(inner_frame, text="Description:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=5)
        self.description_entry = ttk.Entry(inner_frame, width=50)
        self.description_entry.grid(row=row, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        row += 1

        # Household-specific fields frame
        self.household_frame = ttk.LabelFrame(inner_frame, text="Household Settings", padding=10)
        self.household_frame.grid(row=row, column=0, columnspan=2, sticky=tk.W+tk.E, padx=5, pady=10)
        self.household_frame.grid_remove()  # Hidden by default
        row += 1

        self._build_household_fields()

        inner_frame.columnconfigure(1, weight=1)

    def _build_household_fields(self):
        """Build household-specific fields."""
        h_row = 0

        # Rule
        ttk.Label(self.household_frame, text="Rule:").grid(row=h_row, column=0, sticky=tk.W, padx=5, pady=5)
        self.rule_entry = ttk.Entry(self.household_frame, width=40)
        self.rule_entry.grid(row=h_row, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(self.household_frame, text="(from relationship_rules.yaml)", font=('Arial', 9, 'italic')).grid(row=h_row, column=2, sticky=tk.W, padx=5)
        h_row += 1

        # Patterns section
        patterns_label = ttk.Label(self.household_frame, text="Patterns:", font=('Arial', 10, 'bold'))
        patterns_label.grid(row=h_row, column=0, sticky=tk.W, padx=5, pady=(10, 5))
        h_row += 1

        # Patterns list frame
        self.patterns_frame = ttk.Frame(self.household_frame)
        self.patterns_frame.grid(row=h_row, column=0, columnspan=3, sticky=tk.W+tk.E, padx=20, pady=5)
        h_row += 1

        # Add pattern button
        add_pattern_btn = ttk.Button(self.household_frame, text="+ Add Pattern", command=self.add_pattern)
        add_pattern_btn.grid(row=h_row, column=0, columnspan=3, sticky=tk.W, padx=20, pady=5)
        h_row += 1

        # Max households
        ttk.Label(self.household_frame, text="Max Households:").grid(row=h_row, column=0, sticky=tk.W, padx=5, pady=5)
        self.max_households_entry = ttk.Entry(self.household_frame, width=20)
        self.max_households_entry.grid(row=h_row, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(self.household_frame, text="(leave empty for no limit)", font=('Arial', 9, 'italic')).grid(row=h_row, column=2, sticky=tk.W, padx=5)
        h_row += 1

        # Refresh pools
        ttk.Label(self.household_frame, text="Refresh Pools:").grid(row=h_row, column=0, sticky=tk.W, padx=5, pady=5)
        self.refresh_pools_var = tk.BooleanVar()
        ttk.Checkbutton(self.household_frame, variable=self.refresh_pools_var).grid(row=h_row, column=1, sticky=tk.W, padx=5, pady=5)
        h_row += 1

        # Enable demotion
        ttk.Label(self.household_frame, text="Enable Demotion:").grid(row=h_row, column=0, sticky=tk.W, padx=5, pady=5)
        self.enable_demotion_var = tk.BooleanVar()
        ttk.Checkbutton(self.household_frame, variable=self.enable_demotion_var).grid(row=h_row, column=1, sticky=tk.W, padx=5, pady=5)
        h_row += 1

        # Demotion rules section
        demotion_label = ttk.Label(self.household_frame, text="Demotion Rules:", font=('Arial', 10, 'bold'))
        demotion_label.grid(row=h_row, column=0, sticky=tk.W, padx=5, pady=(10, 5))
        h_row += 1

        # Demotion rules list frame
        self.demotion_rules_frame = ttk.Frame(self.household_frame)
        self.demotion_rules_frame.grid(row=h_row, column=0, columnspan=3, sticky=tk.W+tk.E, padx=20, pady=5)
        h_row += 1

        # Add demotion rule button
        add_demotion_btn = ttk.Button(self.household_frame, text="+ Add Demotion Rule", command=self.add_demotion_rule)
        add_demotion_btn.grid(row=h_row, column=0, columnspan=3, sticky=tk.W, padx=20, pady=5)

        self.household_frame.columnconfigure(1, weight=1)

    def add_pattern(self, pattern_value="", assumption=""):
        """Add a pattern input field."""
        pattern_frame = ttk.Frame(self.patterns_frame)
        pattern_frame.pack(fill=tk.X, pady=2)

        ttk.Label(pattern_frame, text="Pattern:").pack(side=tk.LEFT, padx=5)
        pattern_entry = ttk.Entry(pattern_frame, width=30)
        pattern_entry.pack(side=tk.LEFT, padx=5)
        pattern_entry.insert(0, pattern_value)

        ttk.Label(pattern_frame, text="Assumption:").pack(side=tk.LEFT, padx=5)
        assumption_entry = ttk.Entry(pattern_frame, width=30)
        assumption_entry.pack(side=tk.LEFT, padx=5)
        assumption_entry.insert(0, assumption)

        remove_btn = ttk.Button(pattern_frame, text="✕", width=3,
                               command=lambda: self.remove_pattern(pattern_frame))
        remove_btn.pack(side=tk.LEFT, padx=5)

        self.pattern_widgets.append((pattern_frame, pattern_entry, assumption_entry))

    def remove_pattern(self, frame):
        """Remove a pattern."""
        for i, (f, _, _) in enumerate(self.pattern_widgets):
            if f == frame:
                self.pattern_widgets.pop(i)
                frame.destroy()
                break

    def add_demotion_rule(self, from_pattern="", to_rule=""):
        """Add a demotion rule mapping."""
        rule_frame = ttk.Frame(self.demotion_rules_frame)
        rule_frame.pack(fill=tk.X, pady=2)

        ttk.Label(rule_frame, text="From Pattern:").pack(side=tk.LEFT, padx=5)
        from_entry = ttk.Entry(rule_frame, width=25)
        from_entry.pack(side=tk.LEFT, padx=5)
        from_entry.insert(0, from_pattern)

        ttk.Label(rule_frame, text="→ To Rule:").pack(side=tk.LEFT, padx=5)
        to_entry = ttk.Entry(rule_frame, width=25)
        to_entry.pack(side=tk.LEFT, padx=5)
        to_entry.insert(0, to_rule)

        remove_btn = ttk.Button(rule_frame, text="✕", width=3,
                               command=lambda: self.remove_demotion_rule(rule_frame))
        remove_btn.pack(side=tk.LEFT, padx=5)

        self.demotion_rule_widgets.append((rule_frame, from_entry, to_entry))

    def remove_demotion_rule(self, frame):
        """Remove a demotion rule."""
        for i, (f, _, _) in enumerate(self.demotion_rule_widgets):
            if f == frame:
                self.demotion_rule_widgets.pop(i)
                frame.destroy()
                break

    def _on_type_changed(self, event=None):
        """Handle type change."""
        if self.type_combo.get() == "household":
            self.household_frame.grid()
        else:
            self.household_frame.grid_remove()

    def _on_delete(self):
        """Handle delete button."""
        if self.on_delete:
            self.on_delete(self)

    def get_data(self):
        """Get step data as dictionary."""
        data = {
            "name": self.name_entry.get(),
            "type": self.type_combo.get(),
            "description": self.description_entry.get(),
        }

        if self.type_combo.get() == "household":
            data["rule"] = self.rule_entry.get()

            # Get patterns
            patterns = []
            for _, pattern_entry, assumption_entry in self.pattern_widgets:
                pattern = pattern_entry.get().strip()
                assumption = assumption_entry.get().strip()
                if pattern:
                    if assumption:
                        # Pattern with assumption
                        patterns.append({
                            "pattern": pattern,
                            "assumption": assumption
                        })
                    else:
                        # Simple pattern string
                        patterns.append(pattern)
            if patterns:
                data["patterns"] = patterns

            # Max households
            max_hh = self.max_households_entry.get().strip()
            data["max_households"] = int(max_hh) if max_hh and max_hh.isdigit() else None

            data["refresh_pools"] = self.refresh_pools_var.get()
            data["enable_demotion"] = self.enable_demotion_var.get() or None

            # Get demotion rules
            demotion_rules = {}
            for _, from_entry, to_entry in self.demotion_rule_widgets:
                from_pattern = from_entry.get().strip()
                to_rule = to_entry.get().strip()
                if from_pattern and to_rule:
                    demotion_rules[from_pattern] = to_rule
            if demotion_rules:
                data["demotion_rules"] = demotion_rules

        return data

    def load_data(self, data):
        """Load data into the widget."""
        self.name_entry.insert(0, data.get("name", ""))
        self.type_combo.set(data.get("type", "household"))
        self.description_entry.insert(0, data.get("description", ""))

        if data.get("type") == "household":
            self.household_frame.grid()
            self.rule_entry.insert(0, data.get("rule", ""))

            # Load patterns
            for pattern in data.get("patterns", []):
                if isinstance(pattern, dict):
                    # Pattern with assumption
                    pattern_value = pattern.get("pattern", "")
                    assumption = pattern.get("assumption", "")
                    self.add_pattern(pattern_value, assumption)
                else:
                    # Simple pattern string
                    self.add_pattern(pattern)

            # Load max households
            max_hh = data.get("max_households")
            if max_hh is not None:
                self.max_households_entry.insert(0, str(max_hh))

            # Handle boolean values (convert None to False)
            refresh_pools = data.get("refresh_pools")
            self.refresh_pools_var.set(refresh_pools if refresh_pools is not None else False)

            enable_demotion = data.get("enable_demotion")
            self.enable_demotion_var.set(enable_demotion if enable_demotion is not None else False)

            # Load demotion rules
            demotion_rules = data.get("demotion_rules", {})
            if demotion_rules:
                for from_pattern, to_rule in demotion_rules.items():
                    self.add_demotion_rule(from_pattern, to_rule)

    def update_number(self, number):
        """Update step number."""
        self.step_number = number
        for child in self.winfo_children():
            if isinstance(child, ttk.LabelFrame):
                child.config(text=f"Step {number}")
                break


class AllocationStrategyTab(ttk.Frame):
    """Tab for managing allocation strategy."""

    def __init__(self, parent, strategy_path, **kwargs):
        super().__init__(parent, **kwargs)
        self.strategy_path = strategy_path
        self.step_widgets = []

        # Create UI
        self.build_ui()

        # Load existing strategy
        self.load_strategy()

    def build_ui(self):
        """Build the allocation strategy UI."""
        # Top toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        ttk.Label(toolbar, text="Allocation Strategy", font=('Arial', 14, 'bold')).pack(side=tk.LEFT)

        save_btn = ttk.Button(toolbar, text="💾 Save Strategy", command=self.save_strategy)
        save_btn.pack(side=tk.RIGHT, padx=5)

        add_btn = ttk.Button(toolbar, text="+ Add Step", command=self.add_step)
        add_btn.pack(side=tk.RIGHT, padx=5)

        # Scrollable steps area
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.steps_frame = ttk.Frame(canvas)

        self.steps_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_frame = canvas.create_window((0, 0), window=self.steps_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=10)
        scrollbar.pack(side="right", fill="y")

        # Update canvas width on resize
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_frame, width=event.width)

        canvas.bind('<Configure>', on_canvas_configure)

        # Enable mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Empty state label
        self.empty_label = ttk.Label(self.steps_frame, text="No steps added yet.\nClick '+ Add Step' to begin.",
                                     font=('Arial', 12), foreground='gray')
        self.empty_label.pack(pady=50)

    def add_step(self, step_data=None):
        """Add a new step."""
        # Hide empty label
        if self.step_widgets == []:
            self.empty_label.pack_forget()

        step_number = len(self.step_widgets) + 1
        step_widget = StepWidget(self.steps_frame, step_data=step_data,
                                on_delete=self.remove_step, step_number=step_number)
        step_widget.pack(fill=tk.X, padx=10, pady=5)
        self.step_widgets.append(step_widget)

    def remove_step(self, step_widget):
        """Remove a step."""
        if messagebox.askyesno("Delete Step", "Are you sure you want to delete this step?"):
            self.step_widgets.remove(step_widget)
            step_widget.destroy()

            # Renumber remaining steps
            for i, widget in enumerate(self.step_widgets, 1):
                widget.update_number(i)

            # Show empty label if no steps
            if not self.step_widgets:
                self.empty_label.pack(pady=50)

    def load_strategy(self):
        """Load strategy from YAML file."""
        try:
            if os.path.exists(self.strategy_path):
                with open(self.strategy_path, 'r') as f:
                    strategy = yaml.safe_load(f)

                if strategy and "steps" in strategy:
                    for step_data in strategy["steps"]:
                        self.add_step(step_data)
        except Exception as e:
            messagebox.showerror("Load Error", f"Error loading strategy:\n{str(e)}")

    def save_strategy(self):
        """Save strategy to YAML file."""
        try:
            strategy = {
                "enabled": True,
                "steps": [widget.get_data() for widget in self.step_widgets]
            }

            with open(self.strategy_path, 'w') as f:
                yaml.dump(strategy, f, default_flow_style=False, sort_keys=False)

            messagebox.showinfo("Saved", f"Allocation strategy saved successfully! at {str(self.strategy_path)}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Error saving strategy:\n{str(e)}")


class WorldCreatorGUI:
    """Main GUI application for world creation."""

    def __init__(self, root):
        self.root = root
        self.root.title("June Zero - World Creator")
        self.root.geometry("1100x800")

        # Set minimum window size
        self.root.minsize(900, 600)

        # Get project root directory (parent of gui folder)
        self.gui_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(self.gui_dir)

        # Config paths
        self.main_config_path = os.path.join(
            self.project_root,
            "world_specific_code/Modern_Day_UK/config_gui.yaml"
        )
        self.strategy_path = os.path.join(
            self.project_root,
            "yaml/households/allocation_strategy_gui.yaml"
        )

        # Create main container
        main_container = ttk.Frame(root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create paned window for form and console
        paned = ttk.PanedWindow(main_container, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Top section: Configuration tabs
        config_notebook = ttk.Notebook(paned)
        paned.add(config_notebook, weight=3)

        # Tab 1: Main Configuration
        main_config_frame = ttk.Frame(config_notebook)
        config_notebook.add(main_config_frame, text="Main Configuration")
        self.config_form = ConfigForm(main_config_frame, self.main_config_path)
        self.config_form.pack(fill=tk.BOTH, expand=True)

        # Tab 2: Allocation Strategy
        strategy_frame = ttk.Frame(config_notebook)
        config_notebook.add(strategy_frame, text="Allocation Strategy")
        self.strategy_tab = AllocationStrategyTab(strategy_frame, self.strategy_path)
        self.strategy_tab.pack(fill=tk.BOTH, expand=True)

        # Bottom section: Control panel and output
        bottom_frame = ttk.Frame(paned)
        paned.add(bottom_frame, weight=2)

        # Control panel
        control_panel = ttk.Frame(bottom_frame)
        control_panel.pack(side=tk.TOP, fill=tk.X, pady=5)

        # Run button
        self.run_btn = ttk.Button(control_panel, text="▶ Run World Creation",
                                  command=self.run_world_creation)
        self.run_btn.pack(side=tk.LEFT, padx=5)

        # Stop button (disabled by default)
        self.stop_btn = ttk.Button(control_panel, text="⏹ Stop",
                                   command=self.stop_process,
                                   state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # Clear output button
        clear_btn = ttk.Button(control_panel, text="Clear Output",
                             command=self.clear_output)
        clear_btn.pack(side=tk.LEFT, padx=5)

        # Status label
        self.status_label = ttk.Label(control_panel, text="Ready",
                                     font=('Arial', 10))
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # Output console
        output_label = ttk.Label(bottom_frame, text="Output Console:")
        output_label.pack(anchor=tk.W, padx=5)

        self.output_text = scrolledtext.ScrolledText(bottom_frame,
                                                     wrap=tk.WORD,
                                                     height=12,
                                                     font=('Courier', 9),
                                                     bg='#1e1e1e',
                                                     fg='#d4d4d4')
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Process tracking
        self.process = None
        self.process_thread = None

        # Configure tags for colored output
        self.output_text.tag_config('error', foreground='#f48771')
        self.output_text.tag_config('warning', foreground='#dcdcaa')
        self.output_text.tag_config('info', foreground='#4ec9b0')
        self.output_text.tag_config('success', foreground='#4ec9b0')

        # Initial message
        self.log_output("June Zero World Creator GUI initialized.\n", 'info')
        self.log_output("Configure your settings above, then click 'Run World Creation'.\n")

    def clear_output(self):
        """Clear the output console."""
        self.output_text.delete('1.0', tk.END)

    def log_output(self, message, tag=None):
        """Add a message to the output console."""
        self.output_text.insert(tk.END, message, tag)
        self.output_text.see(tk.END)
        self.output_text.update_idletasks()

    def update_status(self, status):
        """Update the status label."""
        self.status_label.config(text=status)
        self.root.update_idletasks()

    def run_world_creation(self):
        """Run the create_world.py script."""
        # Save configs first
        self.config_form.save_config()
        self.strategy_tab.save_strategy()

        # Disable run button, enable stop button
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.update_status("Running...")

        # Clear output
        self.clear_output()
        self.log_output("=" * 60 + "\n", 'info')
        self.log_output("Starting world creation...\n", 'info')
        self.log_output("=" * 60 + "\n", 'info')

        # Run script in separate thread
        self.process_thread = threading.Thread(target=self._run_script_thread)
        self.process_thread.daemon = True
        self.process_thread.start()

    def _run_script_thread(self):
        """Thread function to run the script."""
        try:
            # Get conda environment path
            conda_env = "/opt/homebrew/anaconda3/envs/JuneZero"
            python_path = os.path.join(conda_env, "bin", "python")

            # Check if conda environment exists
            if not os.path.exists(python_path):
                self.log_output(f"\nERROR: Conda environment not found at {conda_env}\n", 'error')
                self.log_output("Please ensure the JuneZero conda environment is set up.\n", 'error')
                self._on_process_complete(1)
                return

            # Path to create_world.py
            script_path = os.path.join(self.project_root, "create_world.py")

            if not os.path.exists(script_path):
                self.log_output(f"\nERROR: Script not found at {script_path}\n", 'error')
                self._on_process_complete(1)
                return

            # Set environment variables
            env = os.environ.copy()
            env['PYTHONHASHSEED'] = '0'

            # Run the script
            self.process = subprocess.Popen(
                [python_path, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=self.project_root,
                env=env
            )

            # Read output line by line
            for line in self.process.stdout:
                # Determine tag based on content
                tag = None
                if 'ERROR' in line or 'Error' in line:
                    tag = 'error'
                elif 'WARNING' in line or 'Warning' in line:
                    tag = 'warning'
                elif 'INFO' in line:
                    tag = 'info'

                self.log_output(line, tag)

            # Wait for process to complete
            return_code = self.process.wait()

            # Log completion
            self.log_output("\n" + "=" * 60 + "\n", 'info')
            if return_code == 0:
                self.log_output("World creation completed successfully!\n", 'success')
            else:
                self.log_output(f"World creation failed with return code {return_code}\n", 'error')
            self.log_output("=" * 60 + "\n", 'info')

            self._on_process_complete(return_code)

        except Exception as e:
            self.log_output(f"\nERROR: {str(e)}\n", 'error')
            self._on_process_complete(1)

    def _on_process_complete(self, return_code):
        """Called when the process completes."""
        # Re-enable run button, disable stop button
        self.run_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

        if return_code == 0:
            self.update_status("Completed successfully")
        else:
            self.update_status("Completed with errors")

        self.process = None

    def stop_process(self):
        """Stop the running process."""
        if self.process:
            response = messagebox.askyesno(
                "Stop Process",
                "Are you sure you want to stop the world creation process?"
            )
            if response:
                self.process.terminate()
                self.log_output("\n\nProcess stopped by user.\n", 'warning')
                self.update_status("Stopped")
                self._on_process_complete(1)

    def on_closing(self):
        """Handle window closing."""
        # Stop any running process
        if self.process:
            self.process.terminate()

        self.root.destroy()


def main():
    """Main entry point for the GUI application."""
    root = tk.Tk()

    # Set theme (use 'clam' for a modern look)
    style = ttk.Style()
    available_themes = style.theme_names()
    if 'aqua' in available_themes:  # macOS
        style.theme_use('aqua')
    elif 'clam' in available_themes:
        style.theme_use('clam')

    app = WorldCreatorGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
