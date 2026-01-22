from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length

class ImportPipelineForm(FlaskForm):
    name = StringField('Pipeline Name', validators=[
        DataRequired(),
        Length(max=100)
    ])
    description = TextAreaField('Description', validators=[
        Length(max=500)
    ])
    script_content = TextAreaField('Python Script', validators=[
        DataRequired()
    ], render_kw={"rows": 20, "style": "font-family: monospace;"})
    submit = SubmitField('Save Pipeline')
