import itertools
from functools import partial

import param

from bokeh.models import Div

from .panels import Panel
from .layout import WidgetBox
from .util import default_label_formatter
from .widgets import (
    LiteralInput, Select, Checkbox, FloatSlider, IntSlider, RangeSlider,
    MultiSelect, DatePicker
)


class ParamPanel(Panel):

    show_labels = param.Boolean(default=True)

    display_threshold = param.Number(default=0,precedence=-10,doc="""
        Parameters with precedence below this value are not displayed.""")

    default_precedence = param.Number(default=1e-8,precedence=-10,doc="""
        Precedence value to use for parameters with no declared precedence.
        By default, zero predecence is available for forcing some parameters
        to the top of the list, and other values above the default_precedence
        values can be used to sort or group parameters arbitrarily.""")

    initializer = param.Callable(default=None, doc="""
        User-supplied function that will be called on initialization,
        usually to update the default Parameter values of the
        underlying parameterized object.""")

    width = param.Integer(default=300, bounds=(0, None), doc="""
        Width of widgetbox the parameter widgets are displayed in.""")

    label_formatter = param.Callable(default=default_label_formatter, allow_None=True,
        doc="Callable used to format the parameter names into widget labels.")

    precedence = 1

    _mapping = {
        param.Parameter:     LiteralInput,
        param.Dict:          LiteralInput,
        param.Selector:      Select,
        param.Boolean:       Checkbox,
        param.Number:        FloatSlider,
        param.Integer:       IntSlider,
        param.Range:         RangeSlider,
        param.ListSelector:  MultiSelect,
        param.Date:          DatePicker,
    }

    @classmethod
    def applies(self, obj):
        return isinstance(obj, param.Parameterized)


    def widget(self, p_name):
        """Get widget for param_name"""
        p_obj = self.object.params(p_name)

        widget_class = self._mapping[type(p_obj)]
        value = getattr(self.object, p_name)

        kw = dict(value=value)

        if self.label_formatter is not None:
            kw['name'] = self.label_formatter(p_name)
        else:
            kw['name'] = p_name

        if hasattr(p_obj, 'get_range') and not isinstance(kw['value'], dict):
            options = named_objs(p_obj.get_range().items())
            value = kw['value']
            lookup = {v: k for k, v in options}
            if isinstance(value, list):
                kw['value'] = [lookup[v] for v in value]
            elif isinstance(p_obj, param.FileSelector) and value is None:
                kw['value'] = ''
            else:
                kw['value'] = lookup[value]
            opt_lookup = {k: v for k, v in options}
            self._widget_options[p_name] = opt_lookup
            options = [(k, k) for k, v in options]
            kw['options'] = options

        if hasattr(p_obj, 'get_soft_bounds'):
            kw['start'], kw['end'] = p_obj.get_soft_bounds()

        widget = widget_class(**kw)
        widget.param.watch('value', 'value', partial(self._apply_change, p_name))
        return widget


    def _apply_change(self, p_name, change):
        setattr(self.object, p_name, change.new)


    def _get_widgets(self):
        """Return name,widget boxes for all parameters (i.e., a property sheet)"""
        params = self.object.params().items()
        key_fn = lambda x: x[1].precedence if x[1].precedence is not None else self.default_precedence
        sorted_precedence = sorted(params, key=key_fn)
        filtered = [(k,p) for (k,p) in sorted_precedence
                    if ((p.precedence is None) or (p.precedence >= self.display_threshold))]
        groups = itertools.groupby(filtered, key=key_fn)
        sorted_groups = [sorted(grp) for (k,grp) in groups]
        ordered_params = [el[0] for group in sorted_groups for el in group]

        # Format name specially
        ordered_params.pop(ordered_params.index('name'))
        widgets = [Panel.to_panel(Div(text='<b>{0}</b>'.format(self.object.name)))]
        widgets += [self.widget(pname) for pname in ordered_params]
        return widgets

    def _get_model(self, doc, root=None, parent=None, comm=None):
        panels = self._get_widgets()
        return WidgetBox(*panels)._get_model(doc, root, parent, comm)

    def _get_root(self, doc, comm=None):
        return self._get_model(doc, comm=comm)


class JSONInit(param.Parameterized):
    """
    Callable that can be passed to Widgets.initializer to set Parameter
    values using JSON. There are three approaches that may be used:
    1. If the json_file argument is specified, this takes precedence.
    2. The JSON file path can be specified via an environment variable.
    3. The JSON can be read directly from an environment variable.
    Here is an easy example of setting such an environment variable on
    the commandline:
    PARAM_JSON_INIT='{"p1":5}' jupyter notebook
    This addresses any JSONInit instances that are inspecting the
    default environment variable called PARAM_JSON_INIT, instructing it to set
    the 'p1' parameter to 5.
    """

    varname = param.String(default='PARAM_JSON_INIT', doc="""
        The name of the environment variable containing the JSON
        specification.""")

    target = param.String(default=None, doc="""
        Optional key in the JSON specification dictionary containing the
        desired parameter values.""")

    json_file = param.String(default=None, doc="""
        Optional path to a JSON file containing the parameter settings.""")


    def __call__(self, parameterized):

        warnobj = param.main if isinstance(parameterized, type) else parameterized
        param_class = (parameterized if isinstance(parameterized, type)
                       else parameterized.__class__)

        target = self.target if self.target is not None else param_class.__name__

        env_var = os.environ.get(self.varname, None)
        if env_var is None and self.json_file is None: return

        if self.json_file or env_var.endswith('.json'):
            try:
                fname = self.json_file if self.json_file else env_var
                spec = json.load(open(os.path.abspath(fname), 'r'))
            except:
                warnobj.warning('Could not load JSON file %r' % spec)
        else:
            spec = json.loads(env_var)

        if not isinstance(spec, dict):
            warnobj.warning('JSON parameter specification must be a dictionary.')
            return

        if target in spec:
            params = spec[target]
        else:
            params = spec

        for name, value in params.items():
           try:
               parameterized.set_param(**{name:value})
           except ValueError as e:
               warnobj.warning(str(e))