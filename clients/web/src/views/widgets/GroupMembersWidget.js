/**
 * This view shows a list of members of a group.
 */
girder.views.GroupMembersWidget = girder.View.extend({
    events: {
        'click a.g-member-name': function (e) {
            var model = this.membersColl.get(
                $(e.currentTarget).parents('li').attr('cid')
            );
            girder.router.navigate('user/' + model.get('_id'), {trigger: true});
        },

        'click a.g-group-member-remove': function (e) {
            var view = this;
            var user = this.membersColl.get(
                $(e.currentTarget).parents('li').attr('cid')
            );

            girder.confirm({
                text: 'Are you sure you want to remove <b> ' + _.escape(user.name()) +
                    '</b> from this group?',
                escapedHtml: true,
                confirmCallback: function () {
                    view.trigger('g:removeMember', user);
                }
            });
        },

        'click .g-promote-moderator': function (e) {
            var cid = $(e.currentTarget).parents('.g-group-members>li')
                                        .attr('cid');
            var user = this.membersColl.get(cid);
            this.model.off('g:promoted').on('g:promoted', function () {
                this.trigger('g:moderatorAdded');
            }, this).promoteUser(user, girder.AccessType.WRITE);
        },

        'click .g-promote-admin': function (e) {
            var cid = $(e.currentTarget).parents('.g-group-members>li')
                                        .attr('cid');
            var user = this.membersColl.get(cid);
            this.model.off('g:promoted').on('g:promoted', function () {
                this.trigger('g:adminAdded');
            }, this).promoteUser(user, girder.AccessType.ADMIN);
        }
    },

    initialize: function (settings) {
        this.model = settings.group;
        this.modsAndAdmins = [];
        var view = this;
        _.each(settings.admins, function (user) {
            view.modsAndAdmins.push(user.id);
        });
        _.each(settings.moderators, function (user) {
            view.modsAndAdmins.push(user.id);
        });
        this.membersColl = new girder.collections.UserCollection();
        this.membersColl.altUrl =
            'group/' + this.model.get('_id') + '/member';
        this.membersColl.on('g:changed', function () {
            this.render();
        }, this).fetch();
    },

    render: function () {
        var members = [];
        for (var i = 0; i < this.membersColl.models.length; i += 1) {
            var member = this.membersColl.models[i];
            if ($.inArray(member.id, this.modsAndAdmins) < 0) {
                members.push(member);
            }
        }
        this.$el.html(girder.templates.groupMemberList({
            group: this.model,
            members: members,
            level: this.model.get('_accessLevel'),
            accessType: girder.AccessType
        }));

        new girder.views.PaginateWidget({
            el: this.$('.g-member-pagination'),
            collection: this.membersColl,
            parentView: this
        }).render();

        this.userSearch = new girder.views.SearchFieldWidget({
            el: this.$('.g-group-invite-container'),
            placeholder: 'Invite a user to join...',
            types: ['user'],
            parentView: this
        }).off().on('g:resultClicked', this._inviteUser, this).render();

        this.$('.g-group-member-remove,.g-group-member-promote').tooltip({
            container: 'body',
            placement: 'left',
            animation: false,
            delay: {show: 100}
        });

        return this;
    },

    /**
     * When user searches and clicks a user, this method is called and a
     * dialog is opened allowing the user to select a role to invite into.
     */
    _inviteUser: function (user) {
        this.userSearch.resetState();

        new girder.views.InviteUserDialog({
            el: $('#g-dialog-container'),
            group: this.model,
            user: user,
            parentView: this
        }).on('g:sendInvite', function (params) {
            this.trigger('g:sendInvite', params);
        }, this).render();
    }
});

girder.views.InviteUserDialog = girder.View.extend({
    events: {
        'click .g-invite-as-member': function () {
            this._sendInvitation(girder.AccessType.READ);
        },

        'click .g-invite-as-moderator': function () {
            this._sendInvitation(girder.AccessType.WRITE);
        },

        'click .g-invite-as-admin': function () {
            this._sendInvitation(girder.AccessType.ADMIN);
        },

        'click .g-add-as-member': function () {
            this._sendInvitation(girder.AccessType.READ, true);
        },

        'click .g-add-as-moderator': function () {
            this._sendInvitation(girder.AccessType.WRITE, true);
        },

        'click .g-add-as-admin': function () {
            this._sendInvitation(girder.AccessType.ADMIN, true);
        }
    },

    initialize: function (settings) {
        this.group = settings.group;
        this.user = settings.user;
    },

    render: function () {
        this.$el.html(girder.templates.groupInviteDialog({
            group: this.group,
            user: this.user,
            level: this.group.get('_accessLevel'),
            accessType: girder.AccessType,
            mayAdd: this.group.mayAddMembers()
        })).girderModal(this);

        return this;
    },

    _sendInvitation: function (level, force) {
        this.$el.modal('hide');
        this.trigger('g:sendInvite', {
            user: this.user,
            group: this.group,
            level: level,
            force: force
        });
    }
});
