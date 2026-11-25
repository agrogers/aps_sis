import {
    Component,
    onPatched,
    onWillUpdateProps,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";

export class SearchableSelect extends Component {
    static template = "aps_sis.SearchableSelect";
    static props = {
        options: Array,
        value: { type: [Number, String, Boolean, Array], optional: true },
        multiple: { type: Boolean, optional: true },
        disabled: { type: Boolean, optional: true },
        placeholder: { type: String, optional: true },
        searchPlaceholder: { type: String, optional: true },
        ariaLabel: { type: String, optional: true },
        clearable: { type: Boolean, optional: true },
        clearLabel: { type: String, optional: true },
        showIconPlaceholder: { type: Boolean, optional: true },
        isOpen: { type: Boolean, optional: true },
        onOpenChange: { type: Function, optional: true },
        resetKey: { type: Number, optional: true },
        onSelectionChange: Function,
    };
    static defaultProps = {
        value: false,
        multiple: false,
        disabled: false,
        placeholder: "Select an option",
        searchPlaceholder: "Search...",
        ariaLabel: "",
        clearable: false,
        clearLabel: "Clear selection",
        showIconPlaceholder: false,
    };

    setup() {
        this.state = useState({ query: "", isOpen: false });
        this.rootRef = useRef("root");
        this.menuRef = useRef("menu");
        this._menuScrollTop = 0;
        this._restoreMenuScroll = false;

        useExternalListener(document, "click", (event) => {
            if (
                this.dropdownIsOpen &&
                !this.rootRef.el?.contains(event.target)
            ) {
                this.closeDropdown();
            }
        });

        onWillUpdateProps((nextProps) => {
            const isControlled =
                this.props.isOpen !== undefined && this.props.onOpenChange;
            if (!isControlled && nextProps.resetKey !== this.props.resetKey) {
                this.state.query = "";
                this.state.isOpen = false;
                this._restoreMenuScroll = false;
            }
        });

        onPatched(() => {
            if (!this.dropdownIsOpen) {
                this._restoreMenuScroll = false;
                return;
            }
            if (this._restoreMenuScroll && this.menuRef.el) {
                this.menuRef.el.scrollTop = this._menuScrollTop;
                this._restoreMenuScroll = false;
            }
        });
    }

    get dropdownIsOpen() {
        return this.props.isOpen !== undefined && this.props.onOpenChange
            ? this.props.isOpen
            : this.state.isOpen;
    }

    get selectedOptions() {
        const values = this.props.multiple
            ? (Array.isArray(this.props.value) ? this.props.value : [])
            : [this.props.value];
        return this.props.options.filter((option) => values.includes(option.value));
    }

    get selectedSummary() {
        const selected = this.selectedOptions;
        if (!selected.length) {
            return this.props.placeholder;
        }
        if (!this.props.multiple || selected.length === 1) {
            return selected[0].label;
        }
        return `${selected.length} selected`;
    }

    get selectedBadge() {
        return this.props.multiple ? false : this.selectedOptions[0]?.badge;
    }

    get filteredOptions() {
        const query = this.state.query.trim().toLowerCase();
        const filtered = query
            ? this.props.options.filter((option) =>
                String(option.label || "").toLowerCase().includes(query)
            )
            : this.props.options;
        return filtered.map((option, index) => ({
            ...option,
            showGroupHeading: Boolean(option.group) &&
                (index === 0 || option.group !== filtered[index - 1].group),
        }));
    }

    getGroupSelectionState(group) {
        const groupOptions = this.props.options.filter((option) => option.group === group);
        const selectedCount = groupOptions.filter((option) => this.isSelected(option)).length;
        if (!selectedCount) {
            return "false";
        }
        return selectedCount === groupOptions.length ? "true" : "mixed";
    }

    getGroupCheckboxClass(group) {
        const selectionState = this.getGroupSelectionState(group);
        if (selectionState === "true") {
            return "fa fa-check-square-o fa-fw";
        }
        if (selectionState === "mixed") {
            return "fa fa-minus-square-o fa-fw";
        }
        return "fa fa-square-o fa-fw";
    }

    onOptionIconError(option, event) {
        const image = event.currentTarget;
        if (option.fallbackIconUrl && image.getAttribute("src") !== option.fallbackIconUrl) {
            image.src = option.fallbackIconUrl;
            return;
        }
        image.style.display = "none";
    }

    toggleGroup(group, event) {
        event.stopPropagation();
        if (!this.props.multiple) {
            return;
        }
        const groupValues = this.props.options
            .filter((option) => option.group === group)
            .map((option) => option.value);
        const values = Array.isArray(this.props.value) ? [...this.props.value] : [];
        const selectedValues = new Set(values);
        const allSelected = groupValues.every((value) => selectedValues.has(value));
        const groupValueSet = new Set(groupValues);

        this.rememberMenuScroll();
        this._restoreMenuScroll = true;
        this.props.onSelectionChange(
            allSelected
                ? values.filter((value) => !groupValueSet.has(value))
                : [...new Set([...values, ...groupValues])]
        );
    }

    isSelected(option) {
        return this.props.multiple
            ? Array.isArray(this.props.value) && this.props.value.includes(option.value)
            : this.props.value === option.value;
    }

    toggleDropdown() {
        if (this.props.disabled) {
            return;
        }
        this.state.query = "";
        if (this.dropdownIsOpen) {
            this.rememberMenuScroll();
        } else {
            this._restoreMenuScroll = true;
        }
        this.setDropdownOpen(!this.dropdownIsOpen);
    }

    setDropdownOpen(isOpen) {
        if (this.props.isOpen !== undefined && this.props.onOpenChange) {
            this.props.onOpenChange(isOpen);
        } else {
            this.state.isOpen = isOpen;
        }
    }

    rememberMenuScroll() {
        const menu = this.menuRef.el;
        if (menu) {
            this._menuScrollTop = menu.scrollTop;
        }
    }

    onSearchKeydown(event) {
        event.stopPropagation();
        if (event.key === "Escape") {
            event.preventDefault();
            this.closeDropdown();
        } else if (event.key === "Enter" && this.filteredOptions.length === 1) {
            event.preventDefault();
            this.selectOption(this.filteredOptions[0]);
        }
    }

    selectOption(option) {
        if (this.props.multiple) {
            const values = Array.isArray(this.props.value) ? [...this.props.value] : [];
            const selected = values.includes(option.value);
            this.props.onSelectionChange(
                selected
                    ? values.filter((value) => value !== option.value)
                    : [...values, option.value]
            );
        } else {
            this.props.onSelectionChange(option.value);
        }
        this.closeDropdown();
    }

    toggleOption(option, event) {
        event.stopPropagation();
        if (!this.props.multiple) {
            this.selectOption(option);
            return;
        }
        const values = Array.isArray(this.props.value) ? [...this.props.value] : [];
        const selected = values.includes(option.value);
        this.rememberMenuScroll();
        this._restoreMenuScroll = true;
        this.props.onSelectionChange(
            selected ? values.filter((value) => value !== option.value) : [...values, option.value]
        );
    }

    clearSelection() {
        this.props.onSelectionChange(this.props.multiple ? [] : false);
        if (!this.props.multiple) {
            this.closeDropdown();
        }
    }

    closeDropdown() {
        this.rememberMenuScroll();
        this.state.query = "";
        this._restoreMenuScroll = false;
        this.setDropdownOpen(false);
    }
}
