/**
 * A simple widget for editing markdown text with a preview tab.
 */
girder.views.MarkdownWidget = girder.View.extend({
    events: {
        'show.bs.tab .g-preview-link': function () {
            girder.renderMarkdown(this.val().trim() || 'Nothing to show',
                                  this.$('.g-markdown-preview'));
        },

        'shown.bs.tab .g-write-link': function () {
            this.$('.g-markdown-text').focus();
        },

        'click .g-browse': function () {
            this.$('.g-file-input').click();
        },

        'change .g-file-input': function (e) {
            var files = e.target.files;

            if (files.length) {
                this.files = files;
                this.filesAdded();
            }
        },

        'dragenter .g-markdown-drop-zone': function (e) {
            e.stopPropagation();
            e.preventDefault();
            e.originalEvent.dataTransfer.dropEffect = 'copy';
            this.$('.g-markdown-text,.g-upload-footer').addClass('dragover');
        },

        'dragleave .g-markdown-drop-zone': function (e) {
            e.stopPropagation();
            e.preventDefault();
            this.$('.g-markdown-text,.g-upload-footer').removeClass('dragover');
        },

        'dragover .g-markdown-drop-zone': function (e) {
            e.originalEvent.dataTransfer.dropEffect = 'copy';
            this.$('.g-markdown-text,.g-upload-footer').addClass('dragover');
        },

        'drop .g-markdown-drop-zone': function (e) {
            e.stopPropagation();
            e.preventDefault();
            this.$('.g-markdown-text,.g-upload-footer').removeClass('dragover');
            this.files = e.originalEvent.dataTransfer.files;
            this.filesAdded();
        }
    },

    /**
     * @param [settings.text=''] Initial markdown text.
     * @param [settings.placeholder=''] Text area placeholder.
     * @param [settings.prefix='markdown'] Prefix for element IDs in case
     *     multiple of these widgets are rendered simultaneously.
     * @param [settings.enableUploads=false] Whether to allow uploading files
     *     inline into the markdown.
     * @param [settings.maxUploadSize=10 MB] Max upload size in bytes.
     * @param [settings.parent] If enableUploads is true, set this to the object
     *     into which files should be uploaded.
     * @param [settings.allowedExtensions=null] If you want to restrict to
     *     certain file extensions, set this to a list of (lowercase) extensions,
     *     not including periods. E.g.: ["png", "jpg", "jpeg"]
     */
    initialize: function (settings) {
        this.text = settings.text || '';
        this.placeholder = settings.placeholder || '';
        this.prefix = settings.prefix || 'markdown';
        this.enableUploads = settings.enableUploads || false;
        this.parent = settings.parent || null;
        this.maxUploadSize = settings.maxUploadSize || 1024 * 1024 * 10;
        this.allowedExtensions = settings.allowedExtensions || null;
        this.files = [];
    },

    filesAdded: function () {
        try {
            this.validateFiles();
        } catch (err) {
            girder.events.trigger('g:alert', {
                type: 'danger',
                text: err.message,
                icon: 'cancel',
                timeout: 5000
            });
            return;
        }

        var file = this.files[0];
        var fileModel = new girder.models.FileModel();

        fileModel.on('g:upload.complete', function () {
            var val = this.$('.g-markdown-text').val();
            val += '![' + file.name + '](' + fileModel.downloadUrl() + ')\n';

            this.$('.g-upload-overlay').addClass('hide');
            this.$('.g-markdown-text').removeAttr('disabled').val(val);

            this.trigger('g:fileUploaded', {
                file: file,
                model: fileModel
            });
        }, this).on('g:upload.progress', function (info) {
            var currentProgress = info.startByte + info.loaded;
            this.$('.g-markdown-upload-progress>.progress-bar').css('width',
                Math.ceil(100 * currentProgress / info.total) + '%');
            this.$('.g-markdown-upload-progress-message').text(
                'Uploading ' + info.file.name + ' - ' +
                   girder.formatSize(currentProgress) + ' / ' +
                   girder.formatSize(info.total)
            );
        }, this).on('g:upload.error', function (info) {
            girder.events.trigger('g:alert', {
                type: 'danger',
                text: info.message,
                icon: 'cancel',
                timeout: 5000
            });
            this.$('.g-upload-overlay').addClass('hide');
            this.$('.g-markdown-text').removeAttr('disabled');
        }, this).on('g:upload.errorStarting', function (info) {
            girder.events.trigger('g:alert', {
                type: 'danger',
                text: info.message,
                icon: 'cancel',
                timeout: 5000
            });
            this.$('.g-upload-overlay').addClass('hide');
            this.$('.g-markdown-text').removeAttr('disabled');
        }, this).upload(this.parent, file);

        this.$('.g-upload-overlay').removeClass('hide');
        this.$('.g-markdown-text').attr('disabled', true);
    },

    /**
     * Validate a selection of files. If invalid, throws an object containing
     * a "message" field.
     */
    validateFiles: function (files) {
        files = files || this.files;

        if (this.files.length !== 1) {
            throw {message: 'Please add only one file at a time.'};
        }

        var file = files[0],
            ext = file.name.split('.').pop().toLowerCase();

        if (this.maxUploadSize && file.size > this.maxUploadSize) {
            throw {
                message: 'That file is too large. You may only attach files ' +
                         'up to ' + girder.formatSize(this.maxUploadSize) + '.'
            };
        }

        if (this.allowedExtensions && !_.contains(this.allowedExtensions, ext)) {
            throw {
                message: 'Only files with the following extensions are allowed: ' +
                         this.allowedExtensions.join(', ') + '.'
            };
        }
    },

    render: function () {
        this.$el.html(girder.templates.markdownWidget({
            text: this.text,
            placeholder: this.placeholder,
            prefix: this.prefix,
            enableUploads: this.enableUploads
        }));

        return this;
    },

    /**
     * Get or set the current markdown text. Call with no arguments to return
     * the current value, or call with one argument to set the value to that.
     */
    val: function () {
        if (arguments.length) {
            return this.$('.g-markdown-text').val(arguments[0]);
        } else {
            return this.$('.g-markdown-text').val();
        }
    }
});
