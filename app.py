'''Streamlit interface for the family progress demonstration.'''

import pandas as pd
import streamlit as st

from src.database import initialize_database, reset_database, set_consent
from src.progress import (
    DIMENSION_LABELS,
    get_available_families,
    get_available_months,
    get_children_for_family,
    get_consent_status,
    get_group_summary,
    get_parent_snapshot,
)


st.set_page_config(page_title='Family Progress', layout='wide')

# Keep the page compact and turn Streamlit's empty header into a branded top bar.
st.markdown(
    '''
    <style>
        html, body, [class*=st-] {
            font-family: Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
        }
        header[data-testid=stHeader] {
            background: transparent;
        }
        .top-nav {
            position: fixed;
            inset: 0 0 auto 0;
            height: 3.75rem;
            display: flex;
            align-items: center;
            padding-left: max(2rem, calc((100vw - 1180px) / 2));
            background: white;
            border-bottom: 1px solid #e5e7eb;
            color: #111827;
            font-size: 1.05rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            z-index: 999;
        }
        .block-container {
            max-width: 1180px;
            padding-top: 4.6rem;
            padding-bottom: 1.5rem;
            line-height: 1.58;
        }
        .block-container h1 {
            font-size: 1.7rem;
            line-height: 1.25;
        }
        .block-container h2 {
            font-size: 1.4rem;
            line-height: 1.3;
            margin-bottom: 0.65rem;
        }
        .block-container h3 {
            font-size: 1.18rem;
            line-height: 1.35;
            margin-bottom: 0.55rem;
        }
        div[data-testid=stMarkdownContainer] p {
            line-height: 1.62;
        }
        div[data-testid=stCaptionContainer] {
            font-size: 0.8rem;
            line-height: 1.55;
        }
        div[data-testid=stMetricValue] {
            font-size: 1.5rem;
        }
        div[data-testid=stMetricLabel] {
            font-size: 0.82rem;
        }
    </style>
    <div class=top-nav>Family Progress</div>
    ''',
    unsafe_allow_html=True,
)

# Create the local SQLite database from the static CSV inputs on first run.
initialize_database()

families = get_available_families()
family_by_id = {family['family_id']: family for family in families}
family_ids = list(family_by_id)

snapshot_tab, safeguards_tab = st.tabs(['Family Snapshot', 'Safeguards'])

with snapshot_tab:
    controls, chart_panel = st.columns([0.8, 2.2], gap='large')

    # Keep all snapshot controls together in the narrow left column.
    with controls:
        st.subheader('Monthly snapshot')
        st.caption('Select one child and month.')
        selected_family_id = st.selectbox(
            'Family',
            family_ids,
            format_func=lambda family_id: family_by_id[family_id]['family_name'],
        )
        family_children = get_children_for_family(selected_family_id)
        child_by_id = {child['child_id']: child for child in family_children}
        selected_child_id = st.selectbox(
            'Child',
            list(child_by_id),
            format_func=lambda child_id: child_by_id[child_id]['first_name'],
        )
        months = get_available_months(selected_child_id)
        selected_month = st.selectbox('Month', months)

    try:
        snapshot = get_parent_snapshot(selected_child_id, selected_month)
    except PermissionError as error:
        with chart_panel:
            st.warning(str(error))
    else:
        # The trend gets the wider right column; summary details sit below both columns.
        with chart_panel:
            st.subheader('{} - {}'.format(snapshot['child_name'], snapshot['month']))
            chart_data = pd.DataFrame(snapshot['weekly']).set_index('session_date')
            chart_data = chart_data.rename(columns=DIMENSION_LABELS)
            st.line_chart(
                chart_data,
                y=list(DIMENSION_LABELS.values()),
                y_label='Score',
                height=280,
            )

        st.write(snapshot['summary'])
        metric_columns = st.columns(4)
        metric_columns[0].metric('Sessions attended', snapshot['sessions_attended'])
        for column, dimension in zip(metric_columns[1:], DIMENSION_LABELS):
            average = snapshot['averages'][dimension]
            column.metric(DIMENSION_LABELS[dimension], f'{average:.1f} / 5')

        # Explain the observed pattern rather than repeating the abstract rule.
        if snapshot['contact']['triggered']:
            st.warning('Follow-up suggested - human review recommended')
            for pattern in snapshot['contact']['patterns']:
                dates_and_scores = ', '.join(
                    f'{date}: {score}'
                    for date, score in zip(pattern['sessions'], pattern['scores'])
                )
                label = DIMENSION_LABELS[pattern['dimension']]
                st.write(f'**{label}:** {dates_and_scores}')
            st.caption(
                'Scores of 2 or lower occurred in consecutive sessions in the same '
                'observation area. This suggests a sustained pattern for a person to '
                'review; it does not diagnose or contact the family automatically.'
            )
        else:
            st.success('No follow-up pattern detected')
            st.caption(
                'There were no scores of 2 or lower in consecutive sessions in the '
                'same observation area. No follow-up is suggested.'
            )

with safeguards_tab:
    consent_panel = st.container(width=650)

    with consent_panel:
        st.subheader('Independent consent')
        st.write(
            'Each family controls how its child\u2019s data may be used. Withdrawing one '
            'purpose does not change the others.'
        )
        consent_family_id = st.selectbox(
            'Family for consent demonstration',
            family_ids,
            format_func=lambda family_id: family_by_id[family_id]['family_name'],
            key='consent_family',
        )
        consent_status = get_consent_status(consent_family_id)
        consent_rows = [
            {
                'Purpose': purpose.replace('_', ' ').title(),
                'Status': 'Granted' if consent_status[purpose] else 'Withdrawn',
            }
            for purpose in (
                'service_delivery',
                'parent_reporting',
                'research_analytics',
            )
        ]
        st.dataframe(pd.DataFrame(consent_rows), hide_index=True, width=430)

        # Offer the inverse action so the consent change is visibly reversible.
        if consent_status['research_analytics']:
            st.caption(
                'Withdrawal excludes every child in this family from group analytics. '
                'It does not change service delivery or the private parent snapshot.'
            )
            if st.button('Withdraw research analytics consent'):
                set_consent(consent_family_id, 'research_analytics', False)
                st.rerun()
        else:
            st.warning('Research analytics consent is withdrawn for this family.')
            if st.button('Restore research analytics consent'):
                set_consent(consent_family_id, 'research_analytics', True)
                st.rerun()

        if consent_status['parent_reporting']:
            st.info('Parent snapshot remains available: parent reporting is granted.')

    st.divider()
    analytics_panel = st.container(width=700)

    with analytics_panel:
        st.subheader('Research analytics')
        all_children = []
        for family in families:
            for child in get_children_for_family(family['family_id']):
                all_children.append({**child, 'family_name': family['family_name']})
        child_by_id = {child['child_id']: child for child in all_children}

        def child_label(child_id):
            child = child_by_id[child_id]
            return '{} - {}'.format(child['first_name'], child['family_name'])

        selected_children = st.multiselect(
            'Children included in the group request',
            list(child_by_id),
            default=list(child_by_id),
            format_func=child_label,
        )
        group_month = get_available_months(all_children[0]['child_id'])[0]
        group = get_group_summary(selected_children, group_month)
        selected_count = group['selected_children']
        eligible_count = group['eligible_children']
        excluded_count = group['excluded_children']

        st.markdown(
            f'**{selected_count} selected \u00b7 '
            f'{eligible_count} eligible for analytics**'
        )
        if excluded_count:
            st.caption(
                f'{excluded_count} excluded because research analytics consent is not active.'
            )

        # Suppressed responses contain no averages, so the UI cannot leak statistics.
        if group['suppressed']:
            st.warning(
                'Results suppressed: group-level views require at least five children.'
            )
        else:
            group_rows = []
            for dimension in DIMENSION_LABELS:
                average = group['averages'][dimension]
                group_rows.append(
                    {
                        'Observation': DIMENSION_LABELS[dimension],
                        'Group average': f'{average:.1f} / 5',
                    }
                )
            st.dataframe(pd.DataFrame(group_rows), hide_index=True, width=500)

    st.divider()
    if st.button('Reset demo data'):
        reset_database()
        st.rerun()
