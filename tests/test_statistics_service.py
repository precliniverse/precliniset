# tests/test_statistics_service.py
"""
Tests unitaires du StatisticsService.
Vérifie l'exécution des tests statistiques sur des DataFrames synthétiques.
"""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def service():
    # Import différé pour éviter l'import circulaire au niveau module
    # (statistics_service → analysis_utils → datatables/__init__ → routes_analysis → statistics_service)
    from app.services.statistics_service import StatisticsService
    return StatisticsService()


@pytest.fixture
def two_group_df():
    """DataFrame avec deux groupes indépendants."""
    np.random.seed(42)
    return pd.DataFrame({
        'value': np.concatenate([
            np.random.normal(10, 2, 20),
            np.random.normal(15, 2, 20),
        ]),
        'group': ['A'] * 20 + ['B'] * 20,
        'subject_id': list(range(40)),
    })


@pytest.fixture
def three_group_df():
    """DataFrame avec trois groupes indépendants."""
    np.random.seed(42)
    return pd.DataFrame({
        'value': np.concatenate([
            np.random.normal(10, 2, 15),
            np.random.normal(15, 2, 15),
            np.random.normal(20, 2, 15),
        ]),
        'group': ['A'] * 15 + ['B'] * 15 + ['C'] * 15,
        'subject_id': list(range(45)),
    })


@pytest.fixture
def repeated_measures_df():
    """DataFrame pour mesures répétées (2 timepoints)."""
    np.random.seed(42)
    n = 15
    subjects = list(range(n)) * 2
    timepoints = ['T1'] * n + ['T2'] * n
    values = np.concatenate([
        np.random.normal(10, 1, n),
        np.random.normal(12, 1, n),
    ])
    return pd.DataFrame({
        'value': values,
        'group': timepoints,
        'subject_id': subjects,
    })


# ---------------------------------------------------------------------------
# Tests des clés spéciales
# ---------------------------------------------------------------------------

def test_execute_test_none_key(test_app, service, two_group_df):
    """La clé 'none' doit retourner un résultat sans erreur ni statistique."""
    with test_app.app_context():
        result = service.execute_test(
            two_group_df, 'none', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is None
    assert result['statistic'] is None


def test_execute_test_summary_only_key(test_app, service, two_group_df):
    """La clé 'summary_only' doit retourner un résultat sans erreur."""
    with test_app.app_context():
        result = service.execute_test(
            two_group_df, 'summary_only', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is None


# ---------------------------------------------------------------------------
# Tests paramétriques — groupes indépendants
# ---------------------------------------------------------------------------

def test_ttest_ind_two_groups(test_app, service, two_group_df):
    """t-test indépendant sur deux groupes bien séparés → p < 0.05."""
    with test_app.app_context():
        result = service.execute_test(
            two_group_df, 'ttest_ind', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is None
    assert result['statistic'] is not None
    assert result['p_value'] is not None
    assert result['p_value'] < 0.05, "Les groupes A et B sont bien séparés, p doit être < 0.05"


def test_anova_one_way_three_groups(test_app, service, three_group_df):
    """ANOVA one-way sur trois groupes bien séparés → p < 0.05."""
    with test_app.app_context():
        result = service.execute_test(
            three_group_df, 'anova_oneway', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is None
    assert result['p_value'] is not None
    assert result['p_value'] < 0.05


def test_anova_one_way_posthoc(test_app, service, three_group_df):
    """ANOVA one-way doit inclure des données post-hoc."""
    with test_app.app_context():
        result = service.execute_test(
            three_group_df, 'anova_oneway', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is None
    # Post-hoc data doit être présent si p < 0.05
    if result['p_value'] is not None and result['p_value'] < 0.05:
        assert result['posthoc_data'] is not None


# ---------------------------------------------------------------------------
# Tests non-paramétriques
# ---------------------------------------------------------------------------

def test_mannwhitneyu_two_groups(test_app, service, two_group_df):
    """Mann-Whitney U sur deux groupes bien séparés → p < 0.05."""
    with test_app.app_context():
        result = service.execute_test(
            two_group_df, 'mannwhitneyu', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is None
    assert result['p_value'] is not None
    assert result['p_value'] < 0.05


def test_kruskal_three_groups(test_app, service, three_group_df):
    """Kruskal-Wallis sur trois groupes bien séparés → p < 0.05."""
    with test_app.app_context():
        result = service.execute_test(
            three_group_df, 'kruskal', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is None
    assert result['p_value'] is not None
    assert result['p_value'] < 0.05


# ---------------------------------------------------------------------------
# Tests mesures répétées
# ---------------------------------------------------------------------------

def test_ttest_rel_repeated(test_app, service, repeated_measures_df):
    """t-test apparié sur mesures répétées → p < 0.05."""
    with test_app.app_context():
        result = service.execute_test(
            repeated_measures_df, 'ttest_rel', 'value', ['group'],
            is_repeated=True, subject_id_col='subject_id',
        )
    assert result['error'] is None
    assert result['p_value'] is not None
    assert result['p_value'] < 0.05


def test_wilcoxon_repeated(test_app, service, repeated_measures_df):
    """Wilcoxon sur mesures répétées → p < 0.05."""
    with test_app.app_context():
        result = service.execute_test(
            repeated_measures_df, 'wilcoxon', 'value', ['group'],
            is_repeated=True, subject_id_col='subject_id',
        )
    assert result['error'] is None
    assert result['p_value'] is not None
    assert result['p_value'] < 0.05


# ---------------------------------------------------------------------------
# Tests de robustesse (données dégénérées)
# ---------------------------------------------------------------------------

def test_empty_dataframe(test_app, service):
    """Un DataFrame vide doit retourner une erreur propre, pas une exception."""
    empty_df = pd.DataFrame({'value': [], 'group': [], 'subject_id': []})
    with test_app.app_context():
        result = service.execute_test(
            empty_df, 'ttest_ind', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is not None


def test_single_group_anova(test_app, service):
    """ANOVA avec un seul groupe doit retourner une erreur propre."""
    single_group_df = pd.DataFrame({
        'value': [1.0, 2.0, 3.0, 4.0, 5.0],
        'group': ['A'] * 5,
        'subject_id': list(range(5)),
    })
    with test_app.app_context():
        result = service.execute_test(
            single_group_df, 'anova_oneway', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is not None


def test_unknown_test_key(test_app, service, two_group_df):
    """Une clé de test inconnue doit retourner une erreur propre."""
    with test_app.app_context():
        result = service.execute_test(
            two_group_df, 'nonexistent_test_xyz', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
        )
    assert result['error'] is not None


def test_exclude_outliers_flag(test_app, service):
    """Le flag exclude_outliers doit réduire le nombre de lignes utilisées."""
    np.random.seed(42)
    df = pd.DataFrame({
        'value': np.concatenate([
            np.random.normal(10, 1, 18),
            [100.0, -100.0],  # outliers extrêmes
            np.random.normal(15, 1, 18),
            [200.0, -200.0],  # outliers extrêmes
        ]),
        'group': ['A'] * 20 + ['B'] * 20,
        'subject_id': list(range(40)),
    })
    with test_app.app_context():
        result_with = service.execute_test(
            df, 'ttest_ind', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
            exclude_outliers=True,
        )
        result_without = service.execute_test(
            df, 'ttest_ind', 'value', ['group'],
            is_repeated=False, subject_id_col='subject_id',
            exclude_outliers=False,
        )
    # Avec exclusion, des outliers doivent avoir été détectés
    assert result_with.get('outliers_excluded_for_test', 0) > 0
    # Les deux doivent retourner un résultat valide
    assert result_with['error'] is None
    assert result_without['error'] is None
