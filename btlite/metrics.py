# $$_ Lines starting with # $$_* autogenerated by jup_mini. Do not modify these
# $$_code
# $$_ %%checkall
import statsmodels.api as smapi
import math
from dataclasses import dataclass
import pandas as pd
from typing import Any
import numpy as np
import btlite as bt
from IPython.display import display  # noqa
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime


import warnings
warnings.filterwarnings("error")


@dataclass
class Metrics:
    returns: np.ndarray
    dates: np.ndarray
    equity: np.ndarray
    amean: float
    std: float
    up_days: int
    down_days: int
    up_pct: float
    gmean: float
    sharpe: float
    sortino: float
    k_ratio: float
    mdd_pct: float
    mdd_dates: tuple[np.datetime64, np.datetime64]
    mar: float
    mdd_pct_3yr: float
    mdd_dates_3yr: tuple[np.datetime64, np.datetime64]
    calmar: float
    annual_rets: pd.DataFrame

    def to_df(self) -> pd.DataFrame:
        '''
        Creates a dataframe making it convenient to view the output of the metrics obtained using the compute_return_metrics function.
        
        Args:
            float_precision: Change if you want to display floats with more or less significant figures than the default, 
                3 significant figures.       
        Returns:
            A one row dataframe with formatted metrics.
        '''
        row: dict[str, Any] = {}
        cols = ['gmean', 'amean', 'std', 'sharpe', 'sortino', 'calmar', 'mar']
        row = {col: getattr(self, col) for col in cols}
        row['up_dwn'] = f'{self.up_days}/{self.down_days}/{self.up_pct:.3g}'
        row['mdd'] = f'{self.mdd_dates[0]}/{self.mdd_dates[1]}/{self.mdd_pct:.3f}'
        row['mdd_3yr'] = f'{self.mdd_dates_3yr[0]}/{self.mdd_dates_3yr[1]}/{self.mdd_pct_3yr:.3g}'
        for annual_ret in self.annual_rets.itertuples():
            row[annual_ret.year] = annual_ret.ret
        df = pd.DataFrame({key: [value] for key, value in row.items()})
        return df


def compute_k_ratio(equity: np.ndarray, periods_per_year: int) -> float:
    '''
    Compute k-ratio (2013 or original versions by Lars Kestner). See https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2230949
    
    Args:
        periods_per_year: 252 for daily values                
    >>> np.random.seed(0)
    >>> t = np.arange(1000)
    >>> ret = np.random.normal(loc = 0.0025, scale = 0.01, size = len(t))
    >>> equity = (1 + ret).cumprod()
    >>> assert(math.isclose(compute_k_ratio(equity, 252), 3.888, abs_tol=0.001))
    '''
    equity = np.log(equity)
    fit = smapi.OLS(endog=equity, exog=np.arange(len(equity)), hasconst=False).fit()
    k_ratio = fit.params[0] * math.sqrt(periods_per_year) / (fit.bse[0] * len(equity))
    return k_ratio


def compute_rolling_dd(equity: np.ndarray) -> np.ndarray:
    '''
    Compute numpy array of rolling drawdown percentage
    '''
    s = pd.Series(equity)
    rolling_max = s.expanding(min_periods=1).max()
    dd = np.where(s >= rolling_max, 0.0, -(s - rolling_max) / rolling_max)
    return dd


def compute_gmean(rets: np.ndarray, periods_per_year: int) -> float:
    gmean_daily = (1 + rets).prod() ** (1 / len(rets)) - 1
    gmean_annual = (1 + gmean_daily) ** periods_per_year - 1
    return gmean_annual


def compute_return_metrics(_dates: np.ndarray,
                           rets: np.ndarray,
                           calendar: bt.Calendar) -> Metrics:  

    '''
    >>> timestamps = np.array(['2024-01-02 15:50', '2024-01-03 15:59', '2024-01-04 15:59']).astype('M8[D]')
    >>> rets = np.array([0.1, -0.1, 0.2])
    >>> calendar = bt.Calendar('NYSE')
    >>> metrics = compute_return_metrics(timestamps, rets, calendar)
    >>> assert math.isclose(metrics.gmean, 1.925665e+06, abs_tol=1)
    >>> assert math.isclose(metrics.amean, 16.8, abs_tol=0.0001)
    >>> assert math.isclose(metrics.std, 1.979899, abs_tol=0.00001)
    >>> assert math.isclose(metrics.sharpe, 8.485281, abs_tol=0.00001)
    >>> assert math.isclose(metrics.sortino, 22.449944, abs_tol=0.00001)
    >>> assert math.isclose(metrics.calmar, 168.0, abs_tol=0.0001)
    >>> assert math.isclose(metrics.mar, 168.0, abs_tol=0.0001)   
    '''
    # daily returns, with annualized metrics
    TRADING_DAYS_PER_YEAR = 252  # daily metrics
    bt.assert_(len(_dates) == len(rets))
    bt.assert_(all(_dates[1:-1] - _dates[0:-2]) > 0., 'timestamps must be monotonically increasing')
    bt.assert_(np.all(rets > -1), f'found returns < -1: {rets[rets <= -1]}')  # type: ignore
    _dates = _dates.astype('M8[D]')
    prev_date = calendar.add_trading_days(_dates[0], -1, 'allow')
    dates = np.concatenate([[prev_date], _dates])
    amean = np.mean(rets) * TRADING_DAYS_PER_YEAR
    std = np.std(rets) * np.sqrt(TRADING_DAYS_PER_YEAR)
    up_days = len(rets[rets > 0])
    down_days = len(rets[rets < 0])
    up_pct = up_days / len(rets)
    gmean = compute_gmean(rets, TRADING_DAYS_PER_YEAR)
    sharpe = np.nan if std == 0 else amean / std
    normalized_rets = np.where(rets > 0.0, 0.0, rets)
    sortino_denom = np.std(normalized_rets) * np.sqrt(TRADING_DAYS_PER_YEAR)
    sortino = np.nan if sortino_denom == 0 else amean / sortino_denom
    equity = np.concatenate([[1.], np.cumprod(1 + rets)])
    k_ratio = compute_k_ratio(equity, TRADING_DAYS_PER_YEAR)
    rolling_dd = compute_rolling_dd(equity)
    mdd_pct = np.max(rolling_dd)
    mdd_date = dates[np.argmax(rolling_dd)]
    mdd_start = dates[(rolling_dd <= 0) & (dates <= mdd_date)][-1]
    mar = math.nan if mdd_pct == 0 else amean / mdd_pct
    start_3yr = dates[-1] - np.timedelta64(365 * 3, 'D')
    dates_3yr = dates[dates >= start_3yr]
    equity_3yr = equity[dates >= start_3yr]
    rolling_dd_3yr = compute_rolling_dd(equity_3yr)
    mdd_pct_3yr = np.max(rolling_dd_3yr)
    mdd_date_3yr = dates_3yr[np.argmax(rolling_dd_3yr)]
    mdd_start_3yr = dates_3yr[(rolling_dd_3yr <= 0) & (dates_3yr <= mdd_date_3yr)][-1]
    calmar = math.nan if mdd_pct_3yr == 0 else amean / mdd_pct_3yr
    ret_df = pd.DataFrame({'date': _dates, 'ret': rets})
    ret_df['year'] = ret_df.date.dt.year
    annual_rets = ret_df[['year', 'ret']].groupby('year', as_index=False).agg(lambda x: compute_gmean(x, TRADING_DAYS_PER_YEAR))
    metrics = Metrics( 
        dates=dates,
        returns=rets,
        equity=equity,
        amean=amean,
        std=std,
        up_days=up_days,
        down_days=down_days,
        up_pct=up_pct,
        gmean=gmean,
        sharpe=sharpe,
        sortino=sortino,
        k_ratio=k_ratio,
        mdd_pct=mdd_pct,
        mdd_dates=(mdd_start, mdd_date),
        mar=mar,
        mdd_pct_3yr=mdd_pct_3yr,
        mdd_dates_3yr=(mdd_start_3yr, mdd_date_3yr),
        calmar=calmar,
        annual_rets=annual_rets)
    return metrics


def plot_metrics(metrics: Metrics, starting_equity=1e6) -> go.Figure:
    fig = make_subplots(rows=3, cols=1)

    equity_trc = go.Scatter(x=metrics.dates, y=metrics.equity * starting_equity, mode='lines')
    fig.add_trace(equity_trc, row=1, col=1)

    fig.add_vrect(x0=metrics.mdd_dates[0], 
                  x1=metrics.mdd_dates[1], 
                  annotation_text="max dd", 
                  annotation_position="top left",
                  annotation=dict(font_size=15),
                  fillcolor="red", 
                  opacity=0.25, 
                  line_width=0)


    fig.add_hline(y=starting_equity, opacity=0.25)

    rolling_dd = compute_rolling_dd(metrics.equity * starting_equity)

    dd_trc = go.Scatter(x=metrics.dates, y=rolling_dd, mode='lines')
    fig.add_trace(dd_trc, row=2, col=1)

    fig.add_vrect(x0=metrics.mdd_dates[0], x1=metrics.mdd_dates[1], fillcolor="red", opacity=0.25, line_width=0, row=2, col=1)

    if metrics.mdd_dates != metrics.mdd_dates_3yr:
        for row in [1, 2]:
            fig.add_vrect(x0=metrics.mdd_dates_3yr[0], 
                        x1=metrics.mdd_dates_3yr[1], 
                        fillcolor='#FF851B', 
                        opacity=0.25, 
                        line_width=0, 
                        row=row, 
                        col=1)
            
    returns = metrics.returns
    years = metrics.dates.astype('M8[Y]')[1:]
    for year in np.unique(years):
        rets = returns[years == year]
        _year = year.astype(datetime.date).year
        fig.add_trace(go.Box(x=rets, boxmean=True, marker_color='gray', line_color='gray', name=_year), row=3, col=1)
    fig.add_trace(go.Box(x=returns, boxmean=True, marker_color='blue', line_color='blue', name='All'), row=3, col=1)
    fig.update_yaxes(title_text="Equity", type="log", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown", row=2, col=1)
    fig.update_yaxes(title_text="Return", row=3, col=1)
    fig.update_layout(showlegend=False)
    return fig


if __name__ == "__main__":
    import doctest
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE)
# $$_end_code
