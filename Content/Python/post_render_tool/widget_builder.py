"""Widget Builder — VP Post-Render Tool.

Creates and opens the EditorUtilityWidget Blueprint asset.
Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

import unreal

# Asset location in Content Browser
WIDGET_PACKAGE_PATH = "/Game/PostRenderTool"
WIDGET_ASSET_NAME = "EUW_PostRenderTool"
WIDGET_FULL_PATH = f"{WIDGET_PACKAGE_PATH}/{WIDGET_ASSET_NAME}"


def widget_exists() -> bool:
    """Check if the EUW Blueprint asset already exists in Content Browser."""
    return unreal.EditorAssetLibrary.does_asset_exist(
        f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"
    )


def create_widget() -> object:
    """Create the EditorUtilityWidgetBlueprint asset.

    If the asset already exists, returns the existing one without overwriting.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint
        The created or existing widget Blueprint asset.
    """
    # Check if already exists
    asset_path = f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.log(f"[widget_builder] Widget already exists: {asset_path}")
        return unreal.EditorAssetLibrary.load_asset(asset_path)

    # Ensure directory
    if not unreal.EditorAssetLibrary.does_directory_exist(WIDGET_PACKAGE_PATH):
        unreal.EditorAssetLibrary.make_directory(WIDGET_PACKAGE_PATH)

    # Create the EditorUtilityWidgetBlueprint using factory
    factory = unreal.EditorUtilityWidgetBlueprintFactory()

    # Set parent class to our Python @uclass
    # Import our widget class — this triggers @uclass registration
    from .widget import OPostRenderToolWidget
    try:
        factory.set_editor_property("parent_class", OPostRenderToolWidget)
    except Exception as exc:
        unreal.log_warning(
            f"[widget_builder] Could not set parent_class via factory: {exc}. "
            "Trying alternative approach..."
        )
        # Alternative: create with default parent, then reparent
        pass

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    widget_bp = asset_tools.create_asset(
        WIDGET_ASSET_NAME,
        WIDGET_PACKAGE_PATH,
        None,  # asset_class — None lets the factory decide
        factory,
    )

    if widget_bp is None:
        raise RuntimeError(
            f"Failed to create EditorUtilityWidgetBlueprint at {WIDGET_FULL_PATH}"
        )

    # If factory didn't accept parent_class, try reparenting
    try:
        current_parent = widget_bp.get_editor_property("parent_class")
        if current_parent != OPostRenderToolWidget:
            # Try reparent API
            if hasattr(unreal, "KismetSystemLibrary"):
                unreal.BlueprintEditorLibrary.reparent_blueprint(
                    widget_bp, OPostRenderToolWidget
                )
                unreal.log("[widget_builder] Reparented to OPostRenderToolWidget.")
    except Exception as exc:
        unreal.log_warning(
            f"[widget_builder] Reparent not available: {exc}. "
            "Widget will use default EditorUtilityWidget parent. "
            "UI must be configured manually in Blueprint Designer."
        )

    # Save the asset
    unreal.EditorAssetLibrary.save_asset(
        widget_bp.get_path_name(), only_if_is_dirty=False
    )
    unreal.log(f"[widget_builder] Widget Blueprint created: {WIDGET_FULL_PATH}")

    return widget_bp


def open_widget() -> None:
    """Open the PostRenderTool widget as an editor tab.

    Creates the widget asset first if it doesn't exist.
    """
    widget_bp = create_widget()

    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        subsystem.spawn_and_register_tab(widget_bp)
        unreal.log("[widget_builder] Widget tab opened.")
    except Exception as exc:
        unreal.log_error(f"[widget_builder] Failed to open widget tab: {exc}")
        # Fallback: try running as Editor Utility Widget directly
        try:
            unreal.EditorUtilityLibrary.run_editor_utility_widget(widget_bp)
            unreal.log("[widget_builder] Widget opened via EditorUtilityLibrary fallback.")
        except Exception as exc2:
            unreal.log_error(
                f"[widget_builder] Fallback also failed: {exc2}. "
                "Please right-click the asset in Content Browser > Run Editor Utility Widget."
            )


def delete_widget() -> bool:
    """Delete the existing widget Blueprint asset (for rebuilding).

    Returns
    -------
    bool
        True if deleted, False if not found.
    """
    asset_path = f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.EditorAssetLibrary.delete_asset(asset_path)
        unreal.log(f"[widget_builder] Widget deleted: {asset_path}")
        return True
    return False


def rebuild_widget() -> object:
    """Delete and recreate the widget Blueprint asset.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint
        The newly created widget Blueprint asset.
    """
    delete_widget()
    return create_widget()
