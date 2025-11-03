#!/usr/bin/env python3
"""
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

        # Main config path
        self.main_config_path = os.path.join(
            self.project_root,
            "world_specific_code/Modern_Day_UK/config.yaml"
        )

        # Create main container
        main_container = ttk.Frame(root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create paned window for form and console
        paned = ttk.PanedWindow(main_container, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Top section: Configuration form
        form_frame = ttk.LabelFrame(paned, text="World Configuration", padding=10)
        paned.add(form_frame, weight=3)

        # Create config form
        self.config_form = ConfigForm(form_frame, self.main_config_path)
        self.config_form.pack(fill=tk.BOTH, expand=True)

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
        # Save config first
        self.config_form.save_config()

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
