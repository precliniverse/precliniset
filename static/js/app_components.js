/**
 * Alpine.js Components for Precliniset
 * 
 * This file contains reusable Alpine.js components for managing:
 * - x-select2: Select2 wrapper directive
 * - formState: Global form state management
 * - WizardStepper: Multi-step wizard navigation
 * - GroupEditor: Group editing logic
 * - AnalysisForm: Analysis form logic
 */

document.addEventListener('alpine:init', () => {
    // ============================================
    // Custom Directive: x-select2
    // Handles Select2 integration with Alpine.js
    // ============================================
    Alpine.directive('select2', (el, { expression, modifiers }, { cleanup }) => {
        const options = modifiers.reduce((acc, mod) => {
            if (mod.includes(':')) {
                const [key, value] = mod.split(':');
                acc[key] = value === 'true' ? true : (value === 'false' ? false : value);
            }
            return acc;
        }, {});

        const dataContext = Alpine.evaluate(el, expression);
        const dataObj = Alpine.evaluate(el, expression.split('.')[0]);

        if (!dataObj) {
            console.error('x-select2: Could not find data object for expression:', expression);
            return;
        }

        const select2Instance = $(el).select2({
            theme: 'bootstrap-5',
            width: '100%',
            placeholder: options.placeholder || 'Select...',
            allowClear: options.clearable === true,
            ...options
        });

        $(el).on('change', function () {
            const value = $(this).val();
            Alpine.evaluate(el, `${expression} = ${JSON.stringify(value)}`);
        });

        Alpine.effect(() => {
            const alpineValue = Alpine.evaluate(el, expression);
            if (alpineValue !== $(el).val()) {
                $(el).val(alpineValue).trigger('change');
            }
        });

        cleanup(() => {
            $(el).select2('destroy');
        });
    });

    // ============================================
    // Global Store: formState
    // ============================================
    Alpine.data('formState', () => ({
        isLoading: false,
        errors: {},

        init() {
            console.log('formState initialized');
        },

        setLoading(value) {
            this.isLoading = value;
        },

        setErrors(errors) {
            this.errors = errors;
        },

        clearErrors() {
            this.errors = {};
        },

        reset() {
            this.isLoading = false;
            this.errors = {};
        }
    }));

    // ============================================
    // Component: WizardStepper
    // ============================================
    Alpine.data('wizardStepper', (config = {}) => ({
        currentStep: config.startAt || 1,
        totalSteps: config.steps || 4,
        isLinear: config.linear || false,
        validationRules: config.validation || {},

        get isFirstStep() {
            return this.currentStep === 1;
        },

        get isLastStep() {
            return this.currentStep === this.totalSteps;
        },

        get progressPercentage() {
            return ((this.currentStep - 1) / (this.totalSteps - 1)) * 100;
        },

        init() {
            console.log('WizardStepper initialized at step', this.currentStep);
        },

        nextStep() {
            if (this.isLastStep) return;
            if (this.isLinear && !this.validateStep(this.currentStep)) return;
            this.currentStep++;
        },

        prevStep() {
            if (this.isFirstStep) return;
            this.currentStep--;
        },

        goToStep(step) {
            if (step < 1 || step > this.totalSteps) return;
            if (this.isLinear && step > this.currentStep) {
                for (let i = this.currentStep; i < step; i++) {
                    if (!this.validateStep(i)) return;
                }
            }
            this.currentStep = step;
        },

        validateStep(step) {
            const rules = this.validationRules[step];
            if (!rules) return true;

            let isValid = true;
            this.errors = {};

            rules.forEach(rule => {
                const field = this.$el.querySelector(`[name="${rule.field}"]`);
                if (!field) return;
                const value = field.value || field.dataset.value;

                if (rule.required && !value) {
                    this.errors[rule.field] = rule.message || 'This field is required';
                    isValid = false;
                }
                if (rule.pattern && !rule.pattern.test(value)) {
                    this.errors[rule.field] = rule.message || 'Invalid format';
                    isValid = false;
                }
            });

            return isValid;
        },

        canProceed() {
            if (!this.isLinear) return true;
            return this.validateStep(this.currentStep);
        }
    }));

    // ============================================
    // Component: GroupEditor
    // ============================================
    Alpine.data('groupEditor', (config) => ({
        isEditing: config.isEditing || false,
        groupId: config.groupId || null,
        isRandomized: config.hasRandomization || false,
        isBlinded: config.isBlinded || false,
        projectId: null,
        modelId: null,
        currentFields: [],
        animalData: [],
        isLoading: false,
        urls: config.urls || {},
        i18n: config.i18n || {},

        get canViewUnblinded() {
            return config.canViewUnblinded || false;
        },

        get blindingKey() {
            return config.blindingKey || {};
        },

        init() {
            console.log('GroupEditor initialized');
            this.currentFields = config.modelFields || [];
            this.animalData = config.existingAnimalData || [];
            this.initSelect2();

            if (this.isEditing) {
                this.projectId = this.$el.querySelector('[name="project"]')?.value || null;
                this.modelId = this.$el.querySelector('[name="model"]')?.value || null;
            }
        },

        initSelect2() {
            const projectSelect = $('#project_select');
            const modelSelect = $('#model_select');
            const eaSelect = $('#ethical_approval_select');

            if (projectSelect.length) {
                projectSelect.select2({
                    theme: 'bootstrap-5',
                    width: '100%',
                    placeholder: this.i18n.selectProject || 'Select Project...',
                    allowClear: true,
                    ajax: {
                        url: this.urls.searchProjects,
                        dataType: 'json',
                        delay: 250,
                        data: (params) => ({
                            q: params.term,
                            page: params.page || 1,
                            show_archived: false
                        }),
                        processResults: (data) => ({
                            results: data.results,
                            pagination: { more: (params.page * 10) < data.total_count }
                        }),
                        cache: true
                    },
                    minimumInputLength: 0
                });

                projectSelect.on('select2:select', (e) => {
                    this.projectId = e.params.data.id;
                    this.updateEADropdown(this.projectId);
                });
            }

            if (modelSelect.length) {
                modelSelect.select2({
                    theme: 'bootstrap-5',
                    width: '100%',
                    allowClear: true
                });

                modelSelect.on('change', async (e) => {
                    this.modelId = $(e.target).val();
                    await this.fetchModelFields(this.modelId);
                });
            }

            if (eaSelect.length) {
                eaSelect.select2({
                    theme: 'bootstrap-5',
                    width: '100%',
                    allowClear: true
                });
            }
        },

        async updateEADropdown(projectId) {
            const eaSelect = $('#ethical_approval_select');
            if (!eaSelect.length) return;

            const currentVal = eaSelect.val();
            eaSelect.empty().append(new Option(this.i18n.loading || 'Loading...', ''));

            if (!projectId || projectId === '0') {
                eaSelect.prop('disabled', true);
                eaSelect.trigger('change');
                return;
            }

            eaSelect.prop('disabled', false);

            try {
                const response = await fetch(this.urls.getEthicalApprovalsForProject.replace('0', projectId));
                const data = await response.json();

                eaSelect.empty().append(new Option('-- Select Ethical Approval --', ''));
                data.forEach(ea => {
                    const newOption = new Option(ea.text, ea.id, false, false);
                    eaSelect.append(newOption);
                });

                const targetId = config.ethicalApprovalId || currentVal;
                if (targetId) eaSelect.val(targetId);
                eaSelect.trigger('change');
            } catch (err) {
                console.error('Error updating EA dropdown:', err);
            }
        },

        async fetchModelFields(modelId) {
            if (!modelId || modelId === '0') return;

            this.isLoading = true;
            try {
                const response = await fetch(this.urls.getModelFields.replace('0', modelId));
                const data = await response.json();

                if (data.success) {
                    this.currentFields = data.fields;
                    this.animalData = [];
                    this.updateTemplateDownload(modelId);
                }
            } catch (e) {
                console.error('Error fetching model fields:', e);
            } finally {
                this.isLoading = false;
            }
        },

        updateTemplateDownload(modelId) {
            const downloadBtn = document.getElementById('download-data-btn');
            if (downloadBtn) {
                downloadBtn.href = this.urls.downloadTemplate.replace('0', modelId);
                downloadBtn.removeAttribute('disabled');
            }
        },

        addAnimalRow() {
            this.animalData.push({});
        },

        removeAnimalRow(index) {
            this.animalData.splice(index, 1);
        },

        duplicateAnimalRow(index) {
            const rowData = { ...this.animalData[index] };
            this.animalData.splice(index + 1, 0, rowData);
        },

        calculateAge(dateOfBirth) {
            if (!dateOfBirth) return '-';
            const dob = new Date(dateOfBirth);
            const today = new Date();
            const diff = Math.floor((today - dob) / (1000 * 60 * 60 * 24));
            if (isNaN(diff) || diff < 0) return '-';
            const weeks = Math.floor(diff / 7);
            return `${diff} days (${weeks} weeks)`;
        },

        async saveGroup(dontUpdateDataTables = false, allowNewCategories = false) {
            this.isLoading = true;

            const form = document.getElementById('group-form');
            const formData = new FormData(form);
            formData.append('is_ajax', 'true');
            if (dontUpdateDataTables) formData.append('update_data_tables', 'no');
            if (allowNewCategories) formData.append('allow_new_categories', 'true');
            formData.append('animal_data', JSON.stringify(this.animalData));

            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();

                if (data.success) {
                    if (!this.isEditing && data.redirect_url) {
                        window.location.href = data.redirect_url;
                    } else {
                        window.location.reload();
                    }
                } else if (data.type === 'new_categories') {
                    this.handleNewCategoriesDiscovered(data.data, dontUpdateDataTables);
                } else {
                    alert(data.message || 'Error saving group.');
                }
            } catch (error) {
                console.error('Error during AJAX save:', error);
                alert('An error occurred while saving.');
            } finally {
                this.isLoading = false;
            }
        },

        handleNewCategoriesDiscovered(categoriesMap, dontUpdateDataTables) {
            this.$dispatch('new-categories-discovered', {
                categories: categoriesMap,
                dontUpdateDataTables
            });
        }
    }));

    // ============================================
    // Component: AnalysisForm
    // Reads config from data attributes on the element
    // ============================================
    // ============================================
    // Component: AnalysisManager (Parent)
    // Manages stage transitions and shared state for analysis form
    // ============================================
    Alpine.data('analysisManager', () => {
        // Read config from data attributes immediately
        const configEl = document.getElementById('analysis-config');
        let formData = {};
        let numericalColumns = [];
        let categoricalColumns = [];

        if (configEl) {
            try {
                // Decode HTML entities before parsing JSON (e.g., " -> ")
                const decodeHtmlEntities = (str) => {
                    if (!str) return null;
                    const textarea = document.createElement('textarea');
                    textarea.innerHTML = str;
                    return textarea.value;
                };

                formData = configEl.dataset.formData ? JSON.parse(decodeHtmlEntities(configEl.dataset.formData)) : {};
                numericalColumns = configEl.dataset.numericalColumns ? JSON.parse(decodeHtmlEntities(configEl.dataset.numericalColumns)) : [];
                categoricalColumns = configEl.dataset.categoricalColumns ? JSON.parse(decodeHtmlEntities(configEl.dataset.categoricalColumns)) : [];
            } catch (e) {
                console.error('Error parsing analysis config:', e);
            }
        }

        // Determine initial stage from hidden input
        // Always start at step 1 for GET requests, use form value for POST redirects
        let currentStage = 'initial_selection';

        // Check if we have analysis results from the data attribute on parent
        const container = document.querySelector('[x-data^="analysisManager()"]');
        const hasAnalysisResults = container && container.dataset.hasAnalysisResults === 'true';

        // Only use form value if we have analysis results (POST scenario)
        // On GET, always start at initial_selection
        if (hasAnalysisResults) {
            const stageInput = document.querySelector('[name="analysis_stage"]');
            if (stageInput && stageInput.value) {
                currentStage = stageInput.value;
            }
        }
        // On GET, explicitly set to initial_selection (already default, but for clarity)

        // Read values from form fields if they exist (for POST reload scenarios)
        let selectedNumericals = formData.numerical_params || [];
        let selectedGroupings = formData.grouping_params || [];

        // Check if form fields have values (from POST)
        const numSelect = document.getElementById('numerical_params');
        const grpSelect = document.getElementById('grouping_params');
        if (numSelect && numSelect.options.length > 0) {
            selectedNumericals = Array.from(numSelect.options).map(o => o.value);
        }
        if (grpSelect && grpSelect.options.length > 0) {
            selectedGroupings = Array.from(grpSelect.options).map(o => o.value);
        }

        return {
            currentStage: currentStage,
            selectedNumericals: selectedNumericals,
            selectedGroupings: selectedGroupings,
            graphType: formData.graph_type || 'bar',
            isRepeatedMeasures: formData.is_repeated_measures || false,
            excludeOutliers: formData.exclude_outliers || false,
            outlierMethod: formData.outlier_method || 'iqr',
            numericalColumns: numericalColumns,
            categoricalColumns: categoricalColumns,

            get allSelectableParams() {
                return [
                    ...this.numericalColumns.map(col => ({ name: col, type: 'numerical' })),
                    ...this.categoricalColumns.map(col => ({ name: col, type: 'categorical' }))
                ];
            },

            get allGroupingParams() {
                return [...this.categoricalColumns, ...this.numericalColumns].sort();
            },

            get showRepeatedMeasures() {
                return this.selectedNumericals.length > 1;
            },

            get groupingSelectedCount() {
                return this.selectedGroupings.length;
            },

            init() {
                console.log('AnalysisManager initialized');
                console.log('  currentStage:', this.currentStage);
                console.log('  numericalColumns:', this.numericalColumns);
                console.log('  categoricalColumns:', this.categoricalColumns);
                console.log('  allSelectableParams:', this.allSelectableParams);
                console.log('  allGroupingParams:', this.allGroupingParams);
            },

            // Stage navigation
            goToStep1() {
                this.currentStage = 'initial_selection';
                const stageInput = document.getElementById('analysis_stage');
                if (stageInput) stageInput.value = 'propose_workflow';
            },

            goToStep2() {
                this.currentStage = 'propose_workflow';
                const stageInput = document.getElementById('analysis_stage');
                if (stageInput) stageInput.value = 'execute_analysis';
            },

            submitAnalysis() {
                const form = document.getElementById('analysis-form');
                const stageInput = document.getElementById('analysis_stage');
                if (stageInput) stageInput.value = 'execute_analysis';
                form.submit();
            },

            // Selection methods
            toggleNumerical(param) {
                const index = this.selectedNumericals.indexOf(param);
                if (index > -1) {
                    this.selectedNumericals.splice(index, 1);
                } else {
                    this.selectedNumericals.push(param);
                }
            },

            toggleGrouping(param) {
                const index = this.selectedGroupings.indexOf(param);
                if (index > -1) {
                    this.selectedGroupings.splice(index, 1);
                } else {
                    this.selectedGroupings.push(param);
                }
            },

            isNumericalSelected(param) {
                return this.selectedNumericals.includes(param);
            },

            isGroupingSelected(param) {
                return this.selectedGroupings.includes(param);
            },

            selectAllNumerical() {
                this.selectedNumericals = [...this.numericalColumns];
            },

            clearAllNumerical() {
                this.selectedNumericals = [];
            },

            syncHiddenSelects() {
                // Sync numerical_params select
                const numSelect = document.getElementById('numerical_params');
                if (numSelect) {
                    numSelect.innerHTML = '';
                    this.selectedNumericals.forEach(param => {
                        const option = document.createElement('option');
                        option.value = param;
                        option.text = param;
                        option.selected = true;
                        numSelect.appendChild(option);
                    });
                }

                // Sync grouping_params select
                const grpSelect = document.getElementById('grouping_params');
                if (grpSelect) {
                    grpSelect.innerHTML = '';
                    this.selectedGroupings.forEach(param => {
                        const option = document.createElement('option');
                        option.value = param;
                        option.text = param;
                        option.selected = true;
                        grpSelect.appendChild(option);
                    });
                }
            },

            submitForm() {
                // Sync hidden selects before validation
                this.syncHiddenSelects();

                const form = document.getElementById('analysis-form');
                if (this.selectedNumericals.length === 0) {
                    alert('Please select at least one parameter to analyze.');
                    return;
                }
                if (this.selectedGroupings.length === 0) {
                    alert('Please select at least one grouping parameter.');
                    return;
                }
                this.goToStep2();
            }
        };
    });

    // ============================================
    // Component: AnalysisFormFromData
    // ============================================
    Alpine.data('analysisFormFromData', () => {
        // These will be populated in init()
        let formData = {};
        let numericalColumns = [];
        let categoricalColumns = [];

        return {
            selectedNumericals: [],
            selectedGroupings: [],
            graphType: 'bar',
            splitBy: null,
            controlGroup: null,
            isRepeatedMeasures: false,
            enableSurvival: false,
            excludeOutliers: false,
            outlierMethod: 'iqr',
            outlierThreshold: 1.5,

            numericalColumns: [],
            categoricalColumns: [],

            get allSelectableParams() {
                return [
                    ...this.numericalColumns.map(col => ({ name: col, type: 'numerical' })),
                    ...this.categoricalColumns.map(col => ({ name: col, type: 'categorical' }))
                ];
            },

            get allGroupingParams() {
                return [...this.categoricalColumns, ...this.numericalColumns].sort();
            },

            get showRepeatedMeasures() {
                return this.selectedNumericals.length > 1;
            },

            get selectedCount() {
                return this.selectedNumericals.length;
            },

            get groupingSelectedCount() {
                return this.selectedGroupings.length;
            },

            init() {
                // Read config from data attributes on this element
                const el = this.$el;
                formData = el.dataset.formData ? JSON.parse(el.dataset.formData) : {};
                numericalColumns = el.dataset.numericalColumns ? JSON.parse(el.dataset.numericalColumns) : [];
                categoricalColumns = el.dataset.categoricalColumns ? JSON.parse(el.dataset.categoricalColumns) : [];

                // Initialize state from config
                this.selectedNumericals = formData.numerical_params || [];
                this.selectedGroupings = formData.grouping_params || [];
                this.graphType = formData.graph_type || 'bar';
                this.isRepeatedMeasures = formData.is_repeated_measures || false;
                this.enableSurvival = formData.enable_survival || false;
                this.excludeOutliers = formData.exclude_outliers || false;
                this.outlierMethod = formData.outlier_method || 'iqr';
                this.outlierThreshold = formData.outlier_threshold || 1.5;
                this.numericalColumns = numericalColumns;
                this.categoricalColumns = categoricalColumns;

                console.log('AnalysisForm initialized');
            },

            toggleNumerical(param) {
                const index = this.selectedNumericals.indexOf(param);
                if (index > -1) {
                    this.selectedNumericals.splice(index, 1);
                } else {
                    this.selectedNumericals.push(param);
                }
            },

            toggleGrouping(param) {
                const index = this.selectedGroupings.indexOf(param);
                if (index > -1) {
                    this.selectedGroupings.splice(index, 1);
                } else {
                    this.selectedGroupings.push(param);
                }
            },

            isNumericalSelected(param) {
                return this.selectedNumericals.includes(param);
            },

            isGroupingSelected(param) {
                return this.selectedGroupings.includes(param);
            },

            selectAllNumerical() {
                this.selectedNumericals = [...this.numericalColumns];
            },

            clearAllNumerical() {
                this.selectedNumericals = [];
            },

            selectAllGroupings() {
                this.selectedGroupings = [...this.categoricalColumns];
            },

            clearAllGroupings() {
                this.selectedGroupings = [];
            },

            submitForm() {
                const form = document.getElementById('analysis-form');
                if (this.selectedNumericals.length === 0) {
                    alert('Please select at least one parameter to analyze.');
                    return;
                }
                if (this.selectedGroupings.length === 0) {
                    alert('Please select at least one grouping parameter.');
                    return;
                }
                form.submit();
            }
        };
    });

    // ============================================
    // Component: AnalysisForm (Original with config object)
    // ============================================
    Alpine.data('analysisForm', (config) => ({
        selectedNumericals: config.formData?.numerical_params || [],
        selectedGroupings: config.formData?.grouping_params || [],
        graphType: config.formData?.graph_type || 'bar',
        splitBy: null,
        controlGroup: null,
        isRepeatedMeasures: config.formData?.is_repeated_measures || false,
        enableSurvival: config.formData?.enable_survival || false,
        excludeOutliers: config.formData?.exclude_outliers || false,
        outlierMethod: config.formData?.outlier_method || 'iqr',
        outlierThreshold: config.formData?.outlier_threshold || 1.5,

        numericalColumns: config.numericalColumns || [],
        categoricalColumns: config.categoricalColumns || [],

        get allSelectableParams() {
            return [
                ...this.numericalColumns.map(col => ({ name: col, type: 'numerical' })),
                ...this.categoricalColumns.map(col => ({ name: col, type: 'categorical' }))
            ];
        },

        get allGroupingParams() {
            return [...this.categoricalColumns, ...this.numericalColumns].sort();
        },

        get showRepeatedMeasures() {
            return this.selectedNumericals.length > 1;
        },

        get selectedCount() {
            return this.selectedNumericals.length;
        },

        get groupingSelectedCount() {
            return this.selectedGroupings.length;
        },

        init() {
            console.log('AnalysisForm initialized');
        },

        toggleNumerical(param) {
            const index = this.selectedNumericals.indexOf(param);
            if (index > -1) {
                this.selectedNumericals.splice(index, 1);
            } else {
                this.selectedNumericals.push(param);
            }
        },

        toggleGrouping(param) {
            const index = this.selectedGroupings.indexOf(param);
            if (index > -1) {
                this.selectedGroupings.splice(index, 1);
            } else {
                this.selectedGroupings.push(param);
            }
        },

        isNumericalSelected(param) {
            return this.selectedNumericals.includes(param);
        },

        isGroupingSelected(param) {
            return this.selectedGroupings.includes(param);
        },

        selectAllNumerical() {
            this.selectedNumericals = [...this.numericalColumns];
        },

        clearAllNumerical() {
            this.selectedNumericals = [];
        },

        selectAllGroupings() {
            this.selectedGroupings = [...this.categoricalColumns];
        },

        clearAllGroupings() {
            this.selectedGroupings = [];
        },

        submitForm() {
            // Validate and submit the form
            const form = document.getElementById('analysis-form');
            if (this.selectedNumericals.length === 0) {
                alert('Please select at least one parameter to analyze.');
                return;
            }
            if (this.selectedGroupings.length === 0) {
                alert('Please select at least one grouping parameter.');
                return;
            }
            form.submit();
        }
    }));

    // ============================================
    // Component: ImportWizard
    // ============================================
    Alpine.data('importWizard', (config) => ({
        currentStep: 1,
        totalSteps: 4,
        file: null,
        fileData: null,
        mapping: {},
        advancedLogic: {},
        animalIdColumn: null,
        templates: [],
        pipelines: [],
        isProcessing: false,

        urls: config.urls || {},
        i18n: config.i18n || {},

        get isFirstStep() {
            return this.currentStep === 1;
        },

        get isLastStep() {
            return this.currentStep === this.totalSteps;
        },

        get progressPercentage() {
            return ((this.currentStep - 1) / (this.totalSteps - 1)) * 100;
        },

        init() {
            console.log('ImportWizard initialized');
        },

        initWizardFromConfig() {
            // Read config from data attributes
            const configEl = document.getElementById('import-wizard-config');
            if (configEl) {
                this.urls = {
                    templates: `/api/v1/import_wizard/templates/${configEl.dataset.protocolId}`,
                    pipelines: `/api/v1/import_wizard/pipelines/${configEl.dataset.protocolId}`,
                    parse: '/api/v1/import_wizard/parse',
                    validateAnimals: '/api/v1/import_wizard/validate_animals',
                    import: '/api/v1/import_wizard/import'
                };
                this.dataTableId = configEl.dataset.dataTableId;
                this.groupId = configEl.dataset.groupId;
            }
            this.loadTemplates();
        },

        async loadTemplates() {
            try {
                const response = await fetch(this.urls.templates.replace('PROTOCOL_ID', config.protocolId));
                if (response.ok) {
                    this.templates = await response.json();
                }
            } catch (e) {
                console.error('Error loading templates:', e);
            }
        },

        async handleStep1() {
            if (!this.file) {
                alert('Please select a file first.');
                return;
            }

            this.isProcessing = true;

            try {
                const formData = new FormData();
                formData.append('file', this.file);

                const response = await fetch(this.urls.parse, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) throw new Error(await response.text());

                this.fileData = await response.json();
                this.currentStep = 2;
            } catch (e) {
                alert('Error parsing file: ' + e.message);
            } finally {
                this.isProcessing = false;
            }
        },

        handleStep2() {
            this.mapping = {};
            this.advancedLogic = {};

            this.$dispatch('mapping-collected', {
                mapping: this.mapping,
                advancedLogic: this.advancedLogic
            });

            this.currentStep = 3;
        },

        async handleStep3() {
            this.isProcessing = true;

            try {
                const response = await fetch(this.urls.validateAnimals, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file_path: this.fileData.file_path,
                        group_id: config.groupId,
                        animal_id_column: this.animalIdColumn
                    })
                });

                const data = await response.json();

                this.$dispatch('validation-complete', data);
                this.currentStep = 4;
            } catch (e) {
                alert('Error validating animals: ' + e.message);
            } finally {
                this.isProcessing = false;
            }
        },

        async finalizeImport() {
            this.isProcessing = true;

            try {
                const response = await fetch(this.urls.import, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file_path: this.fileData.file_path,
                        data_table_id: config.dataTableId,
                        mapping: this.mapping,
                        animal_id_column: this.animalIdColumn
                    })
                });

                if (!response.ok) throw new Error(await response.text());

                const result = await response.json();
                alert(result.message);
                window.location.reload();
            } catch (e) {
                alert('Final import failed: ' + e.message);
            } finally {
                this.isProcessing = false;
            }
        }
    }));
});
